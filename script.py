import math
import asyncio
from datetime import datetime
import re
from getpass import getpass
import subprocess as sp
from configparser import ConfigParser
import logging
import sys
from typing import Optional, Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from textwrap import dedent, indent
from functools import cache

import httpx
import audible
from audible.exceptions import AuthFlowError
from bs4 import BeautifulSoup
from tqdm.asyncio import tqdm


logger = logging.getLogger(__name__)
MARKETPLACES = {
    "us": "audible.com",
    "ca": "audible.ca",
    "uk": "audible.co.uk",
    "au": "audible.com.au",
    "fr": "audble.fr",
    "de": "audible.de",
    "jp": "audible.co.jp",
    "it": "audible.it",
    "in": "audible.in",
    "es": "audible.es",
    "br": "audible.com.br",
}

@dataclass(frozen=True)
class BookInfo:
    title: str
    series: str
    release_date: datetime
    cover_img: str = ''


@dataclass
class Series:
    title: str
    url: str
    latest: Optional[BookInfo] = None

@dataclass(frozen=True)
class Rating:
    title: str
    average_rating: float
    reviewers: int

    def __str__(self):
        return '\n'.join([
            f'{self.title}',
            f'  - average rating: {self.average_rating}',
            f'  - reviews: {self.reviewers}',
        ])

def captcha(url: str):
    sp.run(['python', '-m', 'webbrowser', url])
    return input(f'CAPTCHA {url} :')


def login(locale: str):
    '''
    login to Audible client
    '''
    logger.info('logging in')
    auth_file = '.audible_auth'
    try:
        auth = audible.Authenticator.from_file(auth_file)
        client = audible.Client(auth=auth)
        client.get('library', num_results=1)
    except (FileNotFoundError, AuthFlowError):
        user = input('Username (email): ')
        passwd = getpass()
        auth = audible.Authenticator.from_login(
            user,
            passwd,
            locale=locale,
            with_username=False,
            captcha_callback=captcha,
        )
        auth.register_device()
        auth.to_file(auth_file)
        client = audible.Client(auth=auth)
    return client


# ================================== core =====================================

def get_wishlisted(client: audible.Client) -> list[Rating]:
    wishlisted = 1
    page = 0
    page_size = 50
    wishlist = []
    while page*page_size < wishlisted:
        result = client.get(
            'wishlist',
            num_results=page_size,
            response_groups=','.join([
                'product_desc',
                'rating',
            ]),
            sort_by='-Rating',
            page=page
        )
        if page == 0: wishlisted = result['total_results']
        wishlist.extend(
            Rating(
                book['title'],
                book['rating']['overall_distribution']['average_rating'],
                book['rating']['num_reviews']
            ) for book in result['products']
        )
        page += 1
    return wishlist


def get_series_by_latest_owned_title(client: audible.Client) -> dict[str, Series]:
    logger.info('retrieving library')
    library = client.get(
        'library',
        num_results=1000,
        response_groups=','.join([
            'series',
            'product_desc',
            'product_attrs',
        ]),
        sort_by='-PurchaseDate',
    )
    has_series = [book for book in library['items'] if book.get('series')]
    owned = {}
    for book in has_series:
        temp = book['series'][0]
        series = Series(temp['title'], temp['url'])
        book_info = BookInfo(
            book['title'],
            book['series'][0]['title'],
            datetime.strptime(
                book['release_date'],
                '%Y-%m-%d'
            )
        )
        series.latest = book_info
        series = owned.setdefault(series.title, series)
        if series.latest.release_date < book_info.release_date:
            series.latest = book_info
    return owned


def as_relative(release: datetime) -> str:
    '''
    empty string if book is released
    or time till release rounded down by days
    or not rounded if less than 1 day
    '''
    release = release.replace(hour=17)
    today = datetime.today().replace(microsecond=0)
    if release <= today:
        return ''
    diff = release - today
    if diff.days > 0:
        return f': in {diff.days} days'
    else:
        return f': in {diff}'


async def check_releases(http_client: httpx.AsyncClient, marketplace: str, series: Series) -> list[BookInfo]:
    url = series.url.replace('/pd/', f'https://{marketplace}/series/')
    response = await http_client.get(url, timeout=30, follow_redirects=True)
    logger.info(f"checking {series.title} {response.status_code}")
    page = BeautifulSoup(response.content, 'html.parser')
    releases = page.select('.releaseDateLabel')

    def get_release_date(node) -> datetime:
        return datetime.strptime(
            re.search(
                r'\d+-\d+-\d+',
                node.get_text()
            ).group(0),
            '%d-%m-%Y',
        )

    def get_book_info(node, release_date: datetime) -> BookInfo:
        item = node.find_parent('li')
        title = item.select('.bc-heading a.bc-link')[0].get_text()
        cover_img = item.select('picture img')[0]['src']
        return BookInfo(title, series.title, release_date, cover_img)

    return [
        get_book_info(node, release_date) for node in releases
        if (release_date := get_release_date(node)) > series.latest.release_date
    ]


def display(releases: list[list[BookInfo]]) -> list[str]:
    def by_release_date(b: BookInfo): return (b.release_date, b.series)
    def by_min_release(b: list[BookInfo]): return by_release_date(min(b, key=by_release_date))
    sorted_releases = sorted([r for r in releases if r], key=by_min_release)
    return [
        dedent(f"""
        # {books[0].series} {
          "".join(f"""
          - {book.title} {as_relative(book.release_date)}
          """.rstrip()
          for book in books
        )}
        """.rstrip())
        for books in sorted_releases
    ]


# ======================== config =================================
'''
# format
[user]
marketplace = au

[ignore_series]
1 = series title
2 = series2 title
...
'''

def load_config(filename: str='config.ini') -> ConfigParser:
    '''Loads config file'''
    config = ConfigParser()
    with suppress():
        config.read(filename)
        logger.info(f'Successfully loaded {filename}')
    return config

def save_config(config: ConfigParser, filename: str='config.ini'):
    '''Save config file'''
    with open(filename, 'w') as f:
        config.write(f)
        logger.info(f'Successfully saved {filename}')


# ============================= repl ==================================

commands = {}
repl_command = Callable[[audible.Client, ConfigParser], Coroutine[None, None, list[str]]]

def register_command(name: str) -> Callable[[repl_command], repl_command]:
    def accept(func: repl_command) -> repl_command:
        commands[name] = func
        return func
    return accept

@register_command("help")
async def help(_client: audible.Client, _config: ConfigParser) -> list[str]:
    """Show command list"""
    return [
        f"{name}:\n{indent(func.__doc__.strip(), "  ")}"
        for name, func in commands.items()
    ] + [
        dedent("""\
        quit|exit:
          exit the program
        """)
    ]

@register_command("new")
async def get_(client: audible.Client, config: ConfigParser) -> list[str]:
    """Show latest audiobooks from series in your library"""
    owned = {
        series: latest_owned
        for series, latest_owned in get_series_by_latest_owned_title(client).items()
        if 'ignore_series' not in config
        or series not in config['ignore_series'].values()
    }
    async with httpx.AsyncClient() as http_client:
        new_releases = await tqdm.gather(*(
            check_releases(http_client, MARKETPLACES[config["user"]["marketplace"]], series)
            for series in owned.values()
        ))
    return display(new_releases)

@register_command("rank")
async def rank_reviews(client: audible.Client, _config: ConfigParser) -> list[str]:
    """Rank your wishlist by f(review score, reviewers)"""
    wishlist = get_wishlisted(client)
    log_reviews = {rating.title: math.log(1 + rating.reviewers) for rating in wishlist}
    upper = max(log_reviews.values())
    norm_log_review = {title: 5 * log_review / upper for title, log_review in log_reviews.items()}
    wishlist.sort(
        reverse=True,
        key=lambda rating: rating.average_rating * norm_log_review[rating.title]
    )
    return [str(rating) for rating in wishlist]


def update_locale(config: ConfigParser):
    if not config.has_section("user"): config.add_section("user")
    locale = config.get("user", "marketplace", fallback="")
    while locale not in MARKETPLACES:
        locale = input(dedent(f"""\
        Please choose a marketplace:{
            "".join(
            f"""
            {code}: {domain}
            """.rstrip()
            for code, domain in MARKETPLACES.items())
        }
        > """))
    config.set("user", "marketplace", locale)
    save_config(config)


async def repl():
    config = load_config()
    update_locale(config)

    print("Logging in...")
    client = login(config['user']['marketplace'])

    choice = ""
    while choice not in ["quit", "exit"]:
        choice = input("enter command:\n> ").lower()
        if choice in commands:
            result = await commands[choice](client, config)
            print(*result, sep="\n")
        elif choice not in ["quit", "exit"]:
            print("enter 'help' to show command list.")

if __name__ == '__main__':
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    asyncio.run(repl())

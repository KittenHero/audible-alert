import logging
from getpass import getpass
from datetime import datetime
import subprocess as sp
import re

import audible
from audible.exceptions import AuthFlowError
import httpx
from bs4 import BeautifulSoup

from models import BookInfo, Series, Rating


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


async def check_new_releases_in_series(http_client: httpx.AsyncClient, marketplace: str, series: Series) -> list[BookInfo]:
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

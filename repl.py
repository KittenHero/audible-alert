import readline
import math
from datetime import datetime
from configparser import ConfigParser
from typing import Callable, Coroutine
from textwrap import dedent, indent

import httpx
import audible
from tqdm.asyncio import tqdm

from models import BookInfo
from config import load_config, save_config
from audible_client import (
    MARKETPLACES,
    login,
    get_wishlisted,
    get_series_by_latest_owned_title,
    check_new_releases_in_series,
)


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
            check_new_releases_in_series(http_client, MARKETPLACES[config["user"]["marketplace"]], series)
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

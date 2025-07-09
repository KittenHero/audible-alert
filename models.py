from dataclasses import dataclass
from datetime import datetime
from typing import Optional

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

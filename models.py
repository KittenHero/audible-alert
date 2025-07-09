from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

@dataclass(frozen=True)
class BookInfo:
    asin: str
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
    num_star_ratings: List[int] # ascending order (1* -> 5*)
    reviewers: int

    def __str__(self):
        return '\n'.join([
            f'{self.title}',
            f'  - average rating: {self.average_rating}',
            f'  - rating distribution: {"|".join([f"{5-i}* {count}" for i, count in enumerate(reversed(self.num_star_ratings))])}',
            f'  - reviews: {self.reviewers}',
        ])

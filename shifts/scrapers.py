import abc
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .models import Cinema, Movie, Showtime

class BaseScraper(abc.ABC):
    """
    Abstract base class for cinema scrapers.
    Different cinemas organize their websites differently:
    some by Cinema -> Movie -> Times, others by Movie -> Cinema -> Times.
    The implementations should abstract this away.
    """

    @abc.abstractmethod
    def get_raw_data(self) -> List[Dict[str, Any]]:
        """
        Returns raw unstructured data.
        """
        pass

    @abc.abstractmethod
    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalizes raw data into a standard flat list format:
        [
            {
                'cinema_name': '...',
                'movie_title': '...',
                'datetime': datetime.datetime(...)
            }, ...
        ]
        """
        pass
    
    def fetch_and_save(self):
        raw_data = self.get_raw_data()
        normalized = self.normalize_data(raw_data)
        
        for item in normalized:
            cinema, _ = Cinema.objects.get_or_create(name=item['cinema_name'])
            # standardize title with imdb if necessary (mocked here)
            standardized_title = self.standardize_title(item['movie_title'])
            movie, _ = Movie.objects.get_or_create(title=standardized_title)
            
            Showtime.objects.get_or_create(
                movie=movie,
                cinema=cinema,
                datetime=item['datetime']
            )

    def standardize_title(self, title: str) -> str:
        # TBD: Integrate with IMDB to find original or standard title
        # For now, just a direct return
        return title.strip()

class MockCinepolisScraper(BaseScraper):
    """
    Mock scraper mimicking Cinepolis USA structure.
    """
    def get_raw_data(self) -> List[Dict[str, Any]]:
        # Mock payload: Cinepolis might group by movie first
        now = datetime.now()
        base_movie_date = now.replace(hour=19, minute=0, second=0, microsecond=0)
        
        return [
            {
                "MovieTitle": "Dune: Part Two",
                "Cinemas": [
                    {
                        "Name": "Cinepolis Chelsea",
                        "Showtimes": [
                            base_movie_date + timedelta(days=1),
                            base_movie_date + timedelta(days=1, hours=3),
                        ]
                    }
                ]
            },
            {
                "MovieTitle": "Kung Fu Panda 4",
                "Cinemas": [
                    {
                        "Name": "Cinepolis Chelsea",
                        "Showtimes": [
                            base_movie_date + timedelta(days=1, hours=-2),
                            base_movie_date + timedelta(days=1, hours=4),
                        ]
                    },
                    {
                        "Name": "Cinepolis Dayton",
                        "Showtimes": [
                            base_movie_date + timedelta(days=2),
                        ]
                    }
                ]
            }
        ]

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for movie_node in raw_data:
            m_title = movie_node["MovieTitle"]
            for cinema_node in movie_node["Cinemas"]:
                c_name = cinema_node["Name"]
                for st in cinema_node["Showtimes"]:
                    normalized.append({
                        "movie_title": m_title,
                        "cinema_name": c_name,
                        "datetime": st
                    })
        return normalized

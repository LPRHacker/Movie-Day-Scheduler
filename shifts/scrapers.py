import abc
import requests
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Any
from urllib.parse import quote
from bs4 import BeautifulSoup
from .models import Cinema, Movie, Showtime
from django.utils import timezone


# Fallback trailer search URL used when no direct trailer can be found
# (works without any API key).
#
# NOTE: we deliberately do NOT use https://www.youtube.com/results?search_query=...
# as the fallback -- YouTube serves those pages with a "confirm you're not a bot"
# CAPTCHA (web-abuse block) when opened without an existing YouTube session.
# DuckDuckGo's video search surfaces the same YouTube trailers without blocking.
def trailer_search_url(title: str) -> str:
    return "https://duckduckgo.com/?q=" + quote(title.strip() + " trailer") + "&iax=videos&ia=videos"


def is_fallback_trailer(url: str) -> bool:
    """True if the URL is a generated search fallback (new DuckDuckGo format
    or legacy youtube.com/results format) rather than a direct trailer link."""
    return bool(url) and ("duckduckgo.com" in url or "youtube.com/results" in url)

class BaseScraper(abc.ABC):
    """
    Abstract base class for cinema scrapers.
    """

    def __init__(self, cinema_id_external: str = None):
        self.cinema_id_external = cinema_id_external

    @abc.abstractmethod
    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        """
        Returns raw unstructured data for a specific date.
        """
        pass

    @abc.abstractmethod
    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalizes raw data into a standard flat list format:
        [
            {
                'movie_title': '...',
                'datetime': datetime.datetime(...),
                'duration': 120 (optional)
            }, ...
        ]
        """
        pass
    
    def fetch_and_save(self, cinema_obj: Cinema, target_date: date):
        print(f"SCRAPER: Fetching data for {cinema_obj.name} on {target_date}...")
        raw_data = self.get_raw_data(target_date)
        print(f"SCRAPER: Got {len(raw_data)} raw items.")
        normalized = self.normalize_data(raw_data)
        print(f"SCRAPER: Normalized into {len(normalized)} items.")
        
        # Clear existing showtimes for this cinema and date
        tz = timezone.get_current_timezone()
        day_start = timezone.make_aware(datetime.combine(target_date, datetime.min.time()), tz)
        day_end = timezone.make_aware(datetime.combine(target_date, datetime.max.time()), tz)
        Showtime.objects.filter(cinema=cinema_obj, datetime__range=(day_start, day_end)).delete()

        created_count = 0
        for item in normalized:
            # Skip if not the right date (some APIs return more).
            # Scrapers may tag an item with a 'business_day' (e.g. late-night
            # shows whose eventDateTime rolls past midnight); when present it
            # wins over the datetime's own date.
            item_date = item.get('business_day') or item['datetime'].date()
            if item_date != target_date:
                continue

            standardized_title = self.standardize_title(item['movie_title'])
            duration = item.get('duration', 120)
            
            movie, created = Movie.objects.get_or_create(
                title=standardized_title,
                defaults={
                    'duration_minutes': duration,
                    'poster_url': item.get('poster_url', ''),
                    'trailer_url': item.get('trailer_url', ''),
                    'page_url': item.get('page_url', '')
                }
            )
            # Update if defaults were used
            needs_save = False
            if not created:
                if (not movie.poster_url or "placeholder" in movie.poster_url) and item.get('poster_url'):
                    movie.poster_url = item.get('poster_url')
                    needs_save = True
                if (not movie.trailer_url or is_fallback_trailer(movie.trailer_url)) and item.get('trailer_url'):
                    movie.trailer_url = item.get('trailer_url')
                    needs_save = True
                if (not movie.page_url) and item.get('page_url'):
                    movie.page_url = item.get('page_url')
                    needs_save = True
                if movie.duration_minutes == 120 and duration != 120:
                    movie.duration_minutes = duration
                    needs_save = True
            if needs_save:
                movie.save()
            
            Showtime.objects.get_or_create(
                movie=movie,
                cinema=cinema_obj,
                datetime=item['datetime']
            )
            created_count += 1
        print(f"SCRAPER: Saved {created_count} showtimes to DB.")
        return created_count

    def standardize_title(self, title: str) -> str:
        return title.strip()

class MovieLandScraper(BaseScraper):
    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        url = f"https://movieland.co.il/api/Events?&TheatreId={self.cinema_id_external}&MovieId=&HebrewSubs=&Dubbed=&ThreeD=&isVenueUpgrated=&isForSelectedTheaterOnly=true&isHFR3D=false&isHideVODRent=true"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return []

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for movie_node in raw_data:
            m_title = movie_node.get("Name")
            duration_val = movie_node.get("LengthInMinutes") or movie_node.get("Duration", 120)
            try:
                duration = int(duration_val)
            except:
                duration = 120
            pic = movie_node.get("Pic", "")
            p_url = f"https://movieland.co.il/images/{quote(pic)}" if pic else ""
            trailer = movie_node.get("Trailer") or ""
            movie_id = movie_node.get("MovieId")
            page_url = f"https://movieland.co.il/movie/{movie_id}" if movie_id else ""
            for date_node in movie_node.get("Dates", []):
                st_str = date_node.get("Date")
                try:
                    dt = datetime.fromisoformat(st_str)
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                    normalized.append({
                        "movie_title": m_title,
                        "datetime": dt,
                        "duration": duration,
                        "poster_url": p_url,
                        "trailer_url": trailer,
                        "page_url": page_url
                    })
                except: continue
        return normalized

class HotCinemaScraper(BaseScraper):
    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        url = f"https://hotcinema.co.il/tickets/TheaterEvents?theatreid={self.cinema_id_external}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return []

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for movie_node in raw_data:
            m_title = movie_node.get("MovieName")
            duration_val = movie_node.get("Duration") or movie_node.get("DurationInMinutes", 120)
            try:
                if isinstance(duration_val, str):
                    duration = int(re.sub(r'[^0-9]', '', duration_val))
                else:
                    duration = int(duration_val)
            except:
                duration = 120
            movie_id = movie_node.get("MovieId")
            page_url = f"https://hotcinema.co.il/movie/{movie_id}" if movie_id else ""
            for date_node in movie_node.get("Dates", []):
                st_str = date_node.get("Date")
                try:
                    dt = datetime.fromisoformat(st_str)
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                    normalized.append({
                        "movie_title": m_title,
                        "datetime": dt,
                        "duration": duration,
                        "page_url": page_url
                    })
                except: continue
        return normalized

class CinemaCityScraper(BaseScraper):
    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        days_heb = ["יום א", "יום ב", "יום ג", "יום ד", "יום ה", "יום ו", "יום ש"]
        heb_idx = (target_date.weekday() + 1) % 7
        day_name = days_heb[heb_idx]
        date_str = f"{day_name} {target_date.strftime('%d/%m/%Y')}"
        
        url = f"https://www.cinema-city.co.il/tickets/EventsFlat?TheatreId={self.cinema_id_external}&VenueTypeId=0&date={date_str}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.cinema-city.co.il/"
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            try: return response.json()
            except: return []
        return []

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for movie_node in raw_data:
            m_title = movie_node.get("Name")
            duration_val = movie_node.get("Length") or movie_node.get("Duration", 120)
            try:
                duration = int(duration_val)
            except:
                duration = 120
            date_info = movie_node.get("Dates")
            if date_info:
                st_str = date_info.get("Date")
                try:
                    dt = datetime.strptime(st_str, "%d/%m/%Y %H:%M")
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                    pic = movie_node.get("Pic", "")
                    # Cinema City often uses /Images/Movies/
                    p_url = f"https://www.cinema-city.co.il/Images/Movies/{pic}" if pic else ""
                    normalized.append({
                        "movie_title": m_title,
                        "datetime": dt,
                        "duration": duration,
                        "poster_url": p_url
                    })
                except: continue
        return normalized

class YesPlanetScraper(BaseScraper):
    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        # Correct URL for Planet Cinema API
        url = f"https://www.planetcinema.co.il/il/data-api-service/v1/quickbook/10100/film-events/in-cinema/{self.cinema_id_external}/at-date/{target_date.isoformat()}?attr=&lang=he_IL"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Return the full body: showtimes (events) are a separate
                # top-level list that must be joined with films by filmId.
                return data.get("body", {})
        except: pass
        return {}

    def normalize_data(self, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        normalized = []
        if not isinstance(raw_data, dict):
            return normalized

        films = raw_data.get("films", []) or []
        events = raw_data.get("events", []) or []

        # Current API shape: films and events are two top-level lists joined by
        # event.filmId == film.id.
        if events:
            film_by_id = {str(f.get("id", "")).lower(): f for f in films if f.get("id")}
            for event in events:
                film = film_by_id.get(str(event.get("filmId", "")).lower())
                if not film:
                    continue
                st_str = event.get("eventDateTime")
                try:
                    dt = datetime.fromisoformat(st_str)
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                    normalized.append(self._build_item(film, dt, event.get("businessDay")))
                except: continue
            return normalized

        # Legacy API shape: events nested under each film.
        for movie_node in films:
            for event in movie_node.get("events", []):
                st_str = event.get("eventDateTime")
                try:
                    dt = datetime.fromisoformat(st_str)
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                    normalized.append(self._build_item(movie_node, dt))
                except: continue
        return normalized

    def _build_item(self, film: Dict[str, Any], dt: datetime, business_day=None) -> Dict[str, Any]:
        poster = film.get("posterLink", "")
        if poster and poster.startswith("/"):
            poster = "https://www.planetcinema.co.il" + poster
        item = {
            "movie_title": film.get("name"),
            "datetime": dt,
            "duration": int(film.get("length") or 120),
            "poster_url": poster,
            "trailer_url": film.get("videoLink") or ""
        }
        # Tag the screening day so late-night shows (past midnight) are kept
        # under the date the cinema considers them part of.
        if business_day:
            try:
                item["business_day"] = datetime.fromisoformat(business_day).date()
            except: pass
        return item

class BeitLessinScraper(BaseScraper):
    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        url = "https://www.lessin.co.il/%D7%94%D7%A6%D7%92%D7%95%D7%AA/"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return [response.text]
        except: pass
        return []

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not raw_data: return []
        html = raw_data[0]
        soup = BeautifulSoup(html, 'html.parser')
        normalized = []
        items = soup.find_all('tr', class_='showlistitem')
        for item in items:
            date_str = item.get('data-date')
            if not date_str: continue
            time_link = item.find('a', href=lambda x: x and 'pres.global' in x)
            if not time_link: continue
            time_str = time_link.text.strip()
            title_tag = item.find('td', style=lambda x: x and 'width: 100%' in x)
            if not title_tag:
                 title_tag = item.find('a', href=lambda x: x and '/shows/' in x)
            if not title_tag: continue
            m_title = title_tag.text.strip()
            try:
                dt_str = f"{date_str} {time_str}"
                dt = datetime.strptime(dt_str, "%d-%m-%Y %H:%M")
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
                normalized.append({
                    "movie_title": m_title,
                    "datetime": dt,
                    "duration": 120
                })
            except: continue
        return normalized

class HabimaScraper(BaseScraper):
    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        url = "https://www.habima.co.il/presentations/"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return [response.text]
        except: pass
        return []

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Habima scraping logic placeholder
        return []

class CameriScraper(BaseScraper):
    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        url = "https://www.cameri.co.il/%D7%9C%D7%95%D7%97-%D7%94%D7%95%D7%A4%D7%A2%D7%95%D7%AA/?filter=show"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return [response.text]
        except: pass
        return []

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Cameri scraping logic placeholder
        return []

def get_scraper(cinema_obj: Cinema) -> BaseScraper:
    name = cinema_obj.name.lower()
    loc_id = cinema_obj.location_id
    
    if "movieland" in name or "מובילנד" in name:
        return MovieLandScraper(loc_id or "1292")
    elif "hot cinema" in name or "הוט סינמה" in name:
        return HotCinemaScraper(loc_id or "16")
    elif "cinema city" in name or "סינמה סיטי" in name:
        return CinemaCityScraper(loc_id or "1170")
    elif "yes planet" in name or "יס פלאנט" in name or "planet" in name:
        return YesPlanetScraper(loc_id or "1025")
    elif "בית ליסין" in name or "lessin" in name:
        return BeitLessinScraper()
    elif "הבימה" in name or "habima" in name:
        return HabimaScraper()
    elif "קאמרי" in name or "cameri" in name:
        return CameriScraper()
    return None

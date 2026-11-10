import abc
import json
import requests
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Any
from urllib.parse import quote
from bs4 import BeautifulSoup
from .models import Cinema, Hall, Movie, Showtime
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


# Hall type detection. Ordered: the first matching group wins, so a hall called
# "אולם 2 VIP" is VIP even though its name also contains digits.
_HALL_TYPE_KEYWORDS = (
    (Hall.XD, ('xd', 'imax', 'screenx', 'סינמקס', 'cinemax')),
    (Hall.VIP, ('vip', 'וי איי פי')),
    (Hall.PREMIUM, ('premium', 'prime', 'lounge', 'פרימיום')),
    (Hall.THREE_D, ('3d', 'תלת מימד', 'תלת-מימד')),
)

HALL_TYPE_LABELS = dict(Hall.HALL_TYPES)

# Some feeds append the format to the venue name ("אולם 17(Lounge)"). The hall
# type is tracked separately, so the name is stored as a plain hall name/number.
_HALL_FORMAT_SUFFIX = re.compile(
    r'\s*[\(\[]\s*(?:lounge|prime|premium|vip|xd|imax|3d|screenx|סינמקס|cinemax)\s*[\)\]]\s*$',
    re.IGNORECASE,
)


def clean_hall_name(name: str) -> str:
    """Drop a format hint that was glued to the hall name by the feed."""
    name = (name or '').strip()
    cleaned = _HALL_FORMAT_SUFFIX.sub('', name).strip()
    return cleaned or name


def guess_hall_type(name: str, hints=None) -> str:
    """Infer a hall type from its name and any extra hints (formats, attrs)."""
    haystack = " ".join([name or ''] + list(hints or [])).lower()
    for hall_type, keywords in _HALL_TYPE_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return hall_type
    return Hall.REGULAR


def resolve_hall(cinema_obj: Cinema, item: Dict[str, Any]):
    """
    Return the Hall row for a normalized showtime item, creating it if needed.

    Scrapers may provide a real hall name (Cinema City / Yes Planet expose
    auditorium names) or only format flags (MovieLand / Hot Cinema only expose
    3D/VIP booleans). In the latter case a format-named hall is used so the
    screening is still filterable; regular screenings get no hall at all.
    """
    hints = [str(hint) for hint in (item.get('hall_hints') or []) if hint]
    raw_name = (item.get('hall_name') or '').strip()
    # The type is inferred from the raw feed name (it may mention the format),
    # but only the hall's own name/number is stored.
    hall_type = item.get('hall_type') or guess_hall_type(raw_name, hints)
    name = clean_hall_name(raw_name)

    if not name:
        if hall_type == Hall.REGULAR:
            return None
        name = HALL_TYPE_LABELS.get(hall_type, hall_type)

    hall, created = Hall.objects.get_or_create(
        cinema=cinema_obj,
        name=name,
        defaults={'hall_type': hall_type}
    )
    if not created and hall_type != Hall.REGULAR and hall.hall_type != hall_type:
        hall.hall_type = hall_type
        hall.save(update_fields=['hall_type'])
    return hall

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

            hall = resolve_hall(cinema_obj, item)
            Showtime.objects.get_or_create(
                movie=movie,
                cinema=cinema_obj,
                hall=hall,
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
                    # MovieLand exposes no hall number, only screening flags, so
                    # the format becomes the hall name ("3D", "VIP", ...).
                    flags = []
                    if date_node.get("ThreeD"):
                        flags.append("3D")
                    if date_node.get("IsVip"):
                        flags.append("VIP")
                    normalized.append({
                        "movie_title": m_title,
                        "datetime": dt,
                        "duration": duration,
                        "poster_url": p_url,
                        "trailer_url": trailer,
                        "page_url": page_url,
                        "hall_name": " ".join(flags) or None
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
                    # Hot Cinema has no hall numbers, only format flags.
                    flags = []
                    if date_node.get("IsVIP"):
                        flags.append("VIP")
                    if date_node.get("Is3D") or date_node.get("IsAtmos3D"):
                        flags.append("3D")
                    elif date_node.get("IsAtmos2D"):
                        flags.append("Atmos")
                    normalized.append({
                        "movie_title": m_title,
                        "datetime": dt,
                        "duration": duration,
                        "page_url": page_url,
                        "hall_name": " ".join(flags) or None
                    })
                except: continue
        return normalized

class CinemaCityScraper(BaseScraper):
    """
    Cinema City rebuilt its website (2026): the old
    /tickets/EventsFlat endpoint is gone. Ticketing now runs on a Tyco site
    (tickets.cinema-city.co.il), which exposes a single JSON document holding
    every upcoming presentation for all of its sites. We fetch it once and
    keep the rows matching this cinema's location id.
    """

    API_URL = "https://tickets.cinema-city.co.il/api/presentations"
    # The feed is large and identical for every branch, so one download is
    # shared by all Cinema City scrapers for a few minutes.
    CACHE_SECONDS = 300
    _cache: Dict[str, Any] = {"data": None, "fetched_at": None}

    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        now = timezone.now()
        fetched_at = self._cache.get("fetched_at")
        if self._cache.get("data") is not None and fetched_at is not None \
                and (now - fetched_at).total_seconds() < self.CACHE_SECONDS:
            return self._cache["data"]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        try:
            response = requests.get(self.API_URL, headers=headers, timeout=60)
        except requests.RequestException:
            return []
        if response.status_code != 200:
            return []
        try:
            presentations = response.json().get("presentations", [])
        except ValueError:
            return []
        self._cache["data"] = presentations
        self._cache["fetched_at"] = now
        return presentations

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        try:
            location_id = int(self.cinema_id_external)
        except (TypeError, ValueError):
            location_id = None

        normalized = []
        for presentation in raw_data:
            if location_id is not None and presentation.get("venueLocationId") != location_id:
                continue
            m_title = presentation.get("featureName")
            st_str = presentation.get("dateTime")
            if not m_title or not st_str:
                continue
            try:
                duration = int(presentation.get("durationInMinutes") or 120)
            except (TypeError, ValueError):
                duration = 120
            try:
                dt = timezone.make_aware(
                    datetime.strptime(st_str, "%Y-%m-%d %H:%M"),
                    timezone.get_current_timezone()
                )
            except ValueError:
                continue
            item = {
                "movie_title": m_title,
                "datetime": dt,
                "duration": duration,
                # Cinema City gives every screening a venue (hall) name and a
                # venue type id (30 = VIP).
                "hall_name": (presentation.get("venueName") or "").strip() or None,
                "hall_hints": ["VIP"] if presentation.get("venueTypeId") == 30 else []
            }
            # Late-night screenings are filed under the day the cinema sells
            # them for, which can differ from the clock date.
            business_day = presentation.get("businessDate")
            if business_day:
                try:
                    item["business_day"] = datetime.strptime(business_day, "%Y-%m-%d").date()
                except ValueError:
                    pass
            normalized.append(item)
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
                    normalized.append(self._build_item(film, dt, event.get("businessDay"), event))
                except: continue
            return normalized

        # Legacy API shape: events nested under each film.
        for movie_node in films:
            for event in movie_node.get("events", []):
                st_str = event.get("eventDateTime")
                try:
                    dt = datetime.fromisoformat(st_str)
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                    normalized.append(self._build_item(movie_node, dt, event=event))
                except: continue
        return normalized

    def _build_item(self, film: Dict[str, Any], dt: datetime, business_day=None,
                    event: Dict[str, Any] = None) -> Dict[str, Any]:
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
        # Yes Planet exposes the auditorium plus format attributes (2d/3d/...).
        if event:
            item["hall_name"] = (event.get("auditorium") or event.get("auditoriumTinyName") or "").strip() or None
            item["hall_hints"] = [
                str(attribute) for attribute in (event.get("attributeIds") or [])
                if str(attribute).lower() in ('3d', 'imax', 'vip', 'xd', 'premium')
            ]
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
    """
    Habima renders its timetable client-side from a JSON cache file that its
    WordPress theme (tyco-wp) publishes. That file already contains every show,
    its venue and all of its performance timestamps, so no HTML parsing needed.
    """

    DATA_URL = "https://www.habima.co.il/wp-content/themes/tyco-wp/cache/allShowsData.json"

    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(self.DATA_URL, headers=headers, timeout=30)
            if response.status_code == 200:
                return [response.json()]
        except (requests.RequestException, ValueError):
            pass
        return []

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not raw_data:
            return []
        data = raw_data[0]
        shows = (data.get("shows") or {}).get("he") or {}
        presentations = (data.get("presentations") or {}).get("he") or {}
        tz = timezone.get_current_timezone()

        normalized = []
        for show_key, entries in presentations.items():
            show = shows.get(str(show_key)) or {}
            m_title = show.get("title")
            if not m_title:
                continue
            for entry in entries or []:
                try:
                    dt = datetime.fromtimestamp(int(entry.get("time")), tz)
                except (TypeError, ValueError, OSError):
                    continue
                normalized.append({
                    "movie_title": m_title,
                    "datetime": dt,
                    "duration": 120,
                    "page_url": show.get("url", ""),
                    "poster_url": show.get("img", "")
                })
        return normalized

class CameriScraper(BaseScraper):
    """
    Cameri builds its show calendar from a `calendarEvents` JS array embedded in
    the showtimes page. Each event has a date plus a list of
    [id, "HH:MM", notes, external_id, ..., hall] slots, and the show name lives
    in extendedProps.show_name.
    """

    URL = "https://www.cameri.co.il/%D7%9C%D7%95%D7%97-%D7%94%D7%95%D7%A4%D7%A2%D7%95%D7%AA/?filter=show"

    def get_raw_data(self, target_date: date) -> List[Dict[str, Any]]:
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(self.URL, headers=headers, timeout=30)
            if response.status_code == 200:
                return self._extract_events(response.text)
        except requests.RequestException:
            pass
        return []

    @staticmethod
    def _extract_events(html: str) -> List[Dict[str, Any]]:
        """Pull the embedded `calendarEvents` JSON array out of the page."""
        marker = html.find("calendarEvents")
        if marker < 0:
            return []
        start = html.find("[", marker)
        if start < 0:
            return []

        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(html)):
            char = html[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:index + 1])
                    except ValueError:
                        return []
        return []

    def normalize_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tz = timezone.get_current_timezone()
        normalized = []
        for event in raw_data:
            props = event.get("extendedProps") or {}
            m_title = props.get("show_name")
            day_str = event.get("start")
            if not m_title or not day_str:
                continue
            try:
                event_date = datetime.strptime(day_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            for slot in props.get("times") or []:
                if len(slot) < 2:
                    continue
                try:
                    event_time = datetime.strptime(str(slot[1]), "%H:%M").time()
                except ValueError:
                    continue
                normalized.append({
                    "movie_title": m_title,
                    "datetime": timezone.make_aware(datetime.combine(event_date, event_time), tz),
                    "duration": 120
                })
        return normalized

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

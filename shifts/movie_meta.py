"""
Movie metadata enrichment (no API keys required).

Strategy (priority order):
1. Poster/trailer embedded in the cinema JSON (handled in scrapers.py).
2. Scrape the cinema's own movie page (movie.page_url) once for a real
   poster image and YouTube trailer link.
3. Fallback: a non-blocking DuckDuckGo video search link for the trailer
   (YouTube's /results pages are served with a bot-check CAPTCHA), and a
   clean placeholder for posters (handled in the UI).

Every movie is only scraped once: ``meta_checked`` guards against repeated
requests, and successful results are persisted on the Movie row.
"""
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .models import Movie
from .scrapers import trailer_search_url, is_fallback_trailer

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}


def _extract_youtube(html: str):
    """Return first YouTube watch URL found in HTML, or None."""
    m = re.search(r'(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,})', html)
    if m:
        return "https://www.youtube.com/watch?v=" + m.group(1)
    return None


def _to_absolute(src: str, base_url: str) -> str:
    """Resolve a possibly-relative image URL against the movie page URL."""
    if not src:
        return src
    if src.startswith('//'):
        return 'https:' + src
    if src.startswith('/'):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{src}"
    return src


def _looks_like_logo(url: str) -> bool:
    return any(token in url.lower() for token in ('logo', 'icon', 'banner', 'button', 'facebook', 'instagram'))


def _extract_poster(html: str, page_url: str):
    """Return first plausible movie-poster image URL found in HTML, or None."""
    soup = BeautifulSoup(html, 'html.parser')

    # 1. Images inside a container whose class mentions "poster"
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or ''
        parent = img.parent
        parent_class = ' '.join(parent.get('class') or []) if parent else ''
        if 'poster' in parent_class.lower() and src:
            return _to_absolute(src, page_url)

    # 2. og:image meta tag — but skip it if it's a logo/banner (e.g. Hot Cinema
    #    exposes the site logo as og:image, not the movie poster)
    og = soup.find('meta', property='og:image')
    if og and og.get('content') and not _looks_like_logo(og['content']):
        return og['content']

    # 3. Any reasonably-sized movie image (skip banners/logos/icons)
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or ''
        if not src or _looks_like_logo(src):
            continue
        width = img.get('width')
        try:
            if width and int(width) < 200:
                continue
        except (TypeError, ValueError):
            pass
        return _to_absolute(src, page_url)

    return None


def enrich_movie(movie: Movie, force: bool = False):
    """
    Best-effort enrichment of a movie's poster_url / trailer_url.
    Returns (poster_url, trailer_url) after the attempt.
    """
    if movie.meta_checked and not force:
        return movie.poster_url, movie.trailer_url

    if movie.page_url:
        try:
            resp = requests.get(movie.page_url, headers=UA, timeout=12)
            if resp.status_code == 200:
                html = resp.text
                if not movie.poster_url:
                    poster = _extract_poster(html, movie.page_url)
                    if poster:
                        movie.poster_url = poster
                if not movie.trailer_url or is_fallback_trailer(movie.trailer_url):
                    trailer = _extract_youtube(html)
                    if trailer:
                        movie.trailer_url = trailer
        except requests.RequestException:
            pass

    # Last resort: trailer search link so every movie still has a trailer link
    if not movie.trailer_url:
        movie.trailer_url = trailer_search_url(movie.title)

    movie.meta_checked = True
    try:
        movie.save(update_fields=['poster_url', 'trailer_url', 'meta_checked'])
    except Exception:
        movie.save()

    return movie.poster_url, movie.trailer_url

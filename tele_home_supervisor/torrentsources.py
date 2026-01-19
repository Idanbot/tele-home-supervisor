"""Multi-source torrent search with fallback support.

This module provides fallback alternatives when PirateBay is unavailable.
Each source has its own parsing logic, user-agent spoofing, and magnet extraction.
Uses cloudscraper for Cloudflare-protected sites.
"""

from __future__ import annotations

import html
import logging
import os
import random
import re
from abc import ABC, abstractmethod
from typing import Callable
from urllib.parse import quote, unquote

import requests

try:
    import cloudscraper

    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    cloudscraper = None  # type: ignore
    CLOUDSCRAPER_AVAILABLE = False

logger = logging.getLogger(__name__)

# Rotating user agents to mimic real browsers
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Chrome on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Firefox on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Common trackers for building magnet links
TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://p4p.arenabg.com:1337/announce",
    "udp://tracker.dler.org:6969/announce",
]


def _get_random_user_agent() -> str:
    """Return a random user agent for request spoofing."""
    return random.choice(USER_AGENTS)


def _build_browser_headers(referer: str | None = None) -> dict[str, str]:
    """Build headers that mimic a real browser."""
    headers = {
        "User-Agent": _get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _build_magnet(info_hash: str, name: str) -> str:
    """Build a magnet link from info hash and name."""
    dn = quote(name, safe="")
    trackers = "".join(f"&tr={quote(t, safe='')}" for t in TRACKERS)
    return f"magnet:?xt=urn:btih:{info_hash}&dn={dn}{trackers}"


def _get_cloudscraper_session() -> "cloudscraper.CloudScraper | None":
    """Create a cloudscraper session for bypassing Cloudflare."""
    if not CLOUDSCRAPER_AVAILABLE:
        logger.debug("cloudscraper not available")
        return None
    try:
        scraper = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "desktop": True,
            },
            delay=5,
        )
        return scraper
    except Exception as exc:
        logger.debug("Failed to create cloudscraper session: %s", exc)
        return None


def _fetch_with_cloudscraper(
    url: str,
    referer: str | None = None,
    timeout: int = 20,
) -> str | None:
    """Fetch a URL using cloudscraper to bypass Cloudflare.

    Returns HTML content or None if failed.
    """
    scraper = _get_cloudscraper_session()
    if not scraper:
        return None

    headers = _build_browser_headers(referer)
    try:
        resp = scraper.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()

        # Check if still blocked
        text = resp.text
        if "just a moment" in text.lower() or "cf-chl" in text.lower():
            logger.debug("cloudscraper: still blocked by Cloudflare for %s", url)
            return None

        return text
    except Exception as exc:
        logger.debug("cloudscraper fetch failed for %s: %s", url, exc)
        return None


class TorrentResult:
    """Standardized torrent result across all sources."""

    def __init__(
        self,
        name: str,
        magnet: str,
        seeders: int,
        leechers: int,
        source: str,
        size: str | None = None,
    ):
        self.name = name
        self.magnet = magnet
        self.seeders = seeders
        self.leechers = leechers
        self.source = source
        self.size = size

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "magnet": self.magnet,
            "seeders": self.seeders,
            "leechers": self.leechers,
            "source": self.source,
            "size": self.size,
        }


class TorrentSource(ABC):
    """Abstract base class for torrent sources."""

    name: str = "Unknown"
    enabled: bool = True
    timeout: int = 15

    @abstractmethod
    def search(
        self, query: str, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Search for torrents."""
        pass

    @abstractmethod
    def top(
        self, category: str | None = None, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Get top/trending torrents."""
        pass


class BitSearchSource(TorrentSource):
    """BitSearch.to torrent source.

    A meta-search engine that aggregates from multiple sources.
    Provides HTML-based search with direct magnet links.
    """

    name = "BitSearch"
    base_url = os.environ.get("BITSEARCH_BASE_URL", "https://bitsearch.to")

    # Regex patterns for parsing HTML
    _MAGNET_RE = re.compile(r'href="(magnet:\?[^"]+)"', re.IGNORECASE)
    _SEEDERS_RE = re.compile(
        r'text-green-600">\s*<i[^>]*></i>\s*'
        r'<span class="font-medium">(\d+)</span>\s*'
        r"<span>seeders</span>",
        re.IGNORECASE | re.DOTALL,
    )
    _LEECHERS_RE = re.compile(
        r'text-red-600">\s*<i[^>]*></i>\s*'
        r'<span class="font-medium">(\d+)</span>\s*'
        r"<span>leechers</span>",
        re.IGNORECASE | re.DOTALL,
    )
    _CARD_RE = re.compile(
        r'<li class="card search-result[^"]*"[^>]*>(.*?)</li>',
        re.IGNORECASE | re.DOTALL,
    )

    def _fetch(self, url: str) -> str:
        """Fetch HTML with browser-like headers."""
        headers = _build_browser_headers(self.base_url)
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def _extract_name_from_magnet(self, magnet: str) -> str:
        """Extract torrent name from magnet link's dn parameter."""
        match = re.search(r"dn=([^&]+)", magnet)
        if match:
            name = unquote(match.group(1))
            # Remove [Bitsearch.to] prefix if present
            name = re.sub(r"^\[Bitsearch\.to\]\s*", "", name, flags=re.IGNORECASE)
            return name
        return "Unknown"

    def _parse_results(self, html_text: str) -> list[TorrentResult]:
        """Parse search results from HTML."""
        results: list[TorrentResult] = []

        # Find all magnet links and their positions
        magnets = list(self._MAGNET_RE.finditer(html_text))
        seeders_matches = list(self._SEEDERS_RE.finditer(html_text))
        leechers_matches = list(self._LEECHERS_RE.finditer(html_text))

        # Each result appears twice in the HTML (desktop/mobile), so take every other
        seen_hashes: set[str] = set()

        for magnet_match in magnets:
            magnet = html.unescape(magnet_match.group(1))

            # Extract info hash to deduplicate
            hash_match = re.search(r"btih:([a-fA-F0-9]+)", magnet)
            if not hash_match:
                continue
            info_hash = hash_match.group(1).upper()
            if info_hash in seen_hashes:
                continue
            seen_hashes.add(info_hash)

            name = self._extract_name_from_magnet(magnet)

            # Find corresponding seeders/leechers by position
            pos = magnet_match.start()
            seeders = 0
            leechers = 0

            # Find the closest seeder/leecher after this magnet
            for sm in seeders_matches:
                if sm.start() > pos:
                    try:
                        seeders = int(sm.group(1))
                    except ValueError:
                        pass
                    break

            for lm in leechers_matches:
                if lm.start() > pos:
                    try:
                        leechers = int(lm.group(1))
                    except ValueError:
                        pass
                    break

            results.append(
                TorrentResult(
                    name=name,
                    magnet=magnet,
                    seeders=seeders,
                    leechers=leechers,
                    source=self.name,
                )
            )

        return results

    def search(
        self, query: str, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Search BitSearch.to for torrents."""
        q = (query or "").strip()
        if not q:
            return []

        url = f"{self.base_url}/search?q={quote(q)}&page=1&sort=seeders"
        try:
            html_text = self._fetch(url)
            results = self._parse_results(html_text)
            results = sorted(results, key=lambda r: r.seeders, reverse=True)[:10]
            if results:
                logger.debug("bitsearch search results: %s", len(results))
                return results
        except Exception as exc:
            logger.debug("bitsearch search failed: %s", exc)
            if debug_sink:
                debug_sink("bitsearch search failed", str(exc))

        return []

    def top(
        self, category: str | None = None, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Get trending torrents from BitSearch.

        BitSearch doesn't have a dedicated top page, so we search for
        common trending terms based on category.
        """
        # Map categories to search terms
        category_terms = {
            "movies": "1080p",
            "video": "1080p",
            "hdmovies": "2160p 4k",
            "tv": "S01E01",
            "hdtv": "720p HDTV",
            "music": "FLAC",
            "audio": "MP3 320",
            "games": "PC game",
            "apps": "software",
            None: "2024",  # Default to recent content
        }
        term = category_terms.get(category, category_terms[None])
        return self.search(term, debug_sink)


class EZTVSource(TorrentSource):
    """EZTV.re torrent source for TV shows.

    EZTV provides a JSON API for searching TV shows by IMDB ID or keywords.
    """

    name = "EZTV"
    base_url = os.environ.get("EZTV_BASE_URL", "https://eztv.re")

    def _fetch_json(self, url: str) -> dict:
        """Fetch JSON from EZTV API."""
        headers = {
            "User-Agent": _get_random_user_agent(),
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _parse_results(self, data: dict) -> list[TorrentResult]:
        """Parse EZTV API response."""
        results: list[TorrentResult] = []
        torrents = data.get("torrents", [])

        for item in torrents:
            if not isinstance(item, dict):
                continue

            name = str(item.get("title") or item.get("filename") or "").strip()
            magnet = str(item.get("magnet_url") or "").strip()

            if not name or not magnet:
                continue

            try:
                seeders = int(item.get("seeds") or 0)
                leechers = int(item.get("peers") or 0)
            except ValueError:
                seeders = 0
                leechers = 0

            size = None
            size_bytes = item.get("size_bytes")
            if size_bytes:
                try:
                    size_mb = int(size_bytes) / (1024 * 1024)
                    if size_mb > 1024:
                        size = f"{size_mb / 1024:.1f} GB"
                    else:
                        size = f"{size_mb:.1f} MB"
                except (ValueError, TypeError):
                    pass

            results.append(
                TorrentResult(
                    name=name,
                    magnet=magnet,
                    seeders=seeders,
                    leechers=leechers,
                    source=self.name,
                    size=size,
                )
            )

        return results

    def search(
        self, query: str, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Search EZTV for TV shows.

        Note: EZTV search is limited - it works best with IMDB IDs.
        For general searches, results may be limited.
        """
        q = (query or "").strip()
        if not q:
            return []

        # Check if query is an IMDB ID
        imdb_match = re.match(r"^tt\d+$", q, re.IGNORECASE)

        if imdb_match:
            url = f"{self.base_url}/api/get-torrents?imdb_id={q}&limit=20"
        else:
            # EZTV doesn't have a keyword search API, so we skip
            # Could implement page scraping in the future
            return []

        try:
            data = self._fetch_json(url)
            results = self._parse_results(data)
            results = sorted(results, key=lambda r: r.seeders, reverse=True)[:10]
            if results:
                logger.debug("eztv search results: %s", len(results))
                return results
        except Exception as exc:
            logger.debug("eztv search failed: %s", exc)
            if debug_sink:
                debug_sink("eztv search failed", str(exc))

        return []

    def top(
        self, category: str | None = None, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Get latest torrents from EZTV."""
        # EZTV only has TV content, so category is ignored
        url = f"{self.base_url}/api/get-torrents?limit=20"

        try:
            data = self._fetch_json(url)
            results = self._parse_results(data)
            results = sorted(results, key=lambda r: r.seeders, reverse=True)[:10]
            if results:
                logger.debug("eztv top results: %s", len(results))
                return results
        except Exception as exc:
            logger.debug("eztv top failed: %s", exc)
            if debug_sink:
                debug_sink("eztv top failed", str(exc))

        return []


class X1337Source(TorrentSource):
    """1337x.to torrent source.

    Uses cloudscraper to bypass Cloudflare protection.
    """

    name = "1337x"
    enabled = CLOUDSCRAPER_AVAILABLE  # Enable if cloudscraper is installed
    base_url = os.environ.get("X1337_BASE_URL", "https://1337x.to")

    # Regex patterns for parsing
    _ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    _NAME_RE = re.compile(r'/torrent/\d+/([^/"]+)/', re.IGNORECASE)
    _SEEDS_RE = re.compile(r'<td class="seeds">(\d+)</td>', re.IGNORECASE)
    _LEECHES_RE = re.compile(r'<td class="leeches">(\d+)</td>', re.IGNORECASE)
    _DETAIL_LINK_RE = re.compile(r'<a href="(/torrent/[^"]+)"', re.IGNORECASE)

    def _fetch(self, url: str) -> str:
        """Fetch HTML using cloudscraper to bypass Cloudflare."""
        # Try cloudscraper first
        html_text = _fetch_with_cloudscraper(
            url, referer=self.base_url, timeout=self.timeout
        )
        if html_text:
            return html_text

        # Fallback to regular requests (may fail on Cloudflare)
        headers = _build_browser_headers(self.base_url)
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def _get_magnet_from_detail_page(self, detail_url: str) -> str | None:
        """Fetch the magnet link from a torrent detail page."""
        try:
            html_text = self._fetch(detail_url)
            magnet_match = re.search(r'href="(magnet:\?[^"]+)"', html_text)
            if magnet_match:
                return html.unescape(magnet_match.group(1))
        except Exception as exc:
            logger.debug("1337x detail page fetch failed: %s", exc)
        return None

    def _parse_search_results(self, html_text: str) -> list[dict]:
        """Parse search results (without magnets yet)."""
        results: list[dict] = []

        for row in self._ROW_RE.findall(html_text):
            detail_match = self._DETAIL_LINK_RE.search(row)
            seeds_match = self._SEEDS_RE.search(row)
            leeches_match = self._LEECHES_RE.search(row)

            if not detail_match:
                continue

            detail_path = detail_match.group(1)
            name_match = self._NAME_RE.search(detail_path)
            name = unquote(name_match.group(1)).replace("-", " ") if name_match else ""

            try:
                seeders = int(seeds_match.group(1)) if seeds_match else 0
                leechers = int(leeches_match.group(1)) if leeches_match else 0
            except ValueError:
                seeders = 0
                leechers = 0

            results.append(
                {
                    "name": name,
                    "detail_url": f"{self.base_url}{detail_path}",
                    "seeders": seeders,
                    "leechers": leechers,
                }
            )

        return results

    def search(
        self, query: str, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Search 1337x for torrents."""
        if not self.enabled:
            return []

        q = (query or "").strip()
        if not q:
            return []

        url = f"{self.base_url}/search/{quote(q)}/1/"
        try:
            html_text = self._fetch(url)

            # Check for Cloudflare block
            if "just a moment" in html_text.lower() or "cf-chl" in html_text.lower():
                raise RuntimeError("1337x blocked by Cloudflare")

            partial_results = self._parse_search_results(html_text)
            partial_results = sorted(
                partial_results, key=lambda r: r["seeders"], reverse=True
            )[:10]

            results: list[TorrentResult] = []
            for item in partial_results:
                magnet = self._get_magnet_from_detail_page(item["detail_url"])
                if magnet:
                    results.append(
                        TorrentResult(
                            name=item["name"],
                            magnet=magnet,
                            seeders=item["seeders"],
                            leechers=item["leechers"],
                            source=self.name,
                        )
                    )

            if results:
                logger.debug("1337x search results: %s", len(results))
                return results

        except Exception as exc:
            logger.debug("1337x search failed: %s", exc)
            if debug_sink:
                debug_sink("1337x search failed", str(exc))

        return []

    def top(
        self, category: str | None = None, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Get trending torrents from 1337x."""
        if not self.enabled:
            return []

        # 1337x top categories
        category_paths = {
            "movies": "/top-100-movies",
            "video": "/top-100-movies",
            "tv": "/top-100-television",
            "hdtv": "/top-100-television",
            "music": "/top-100-music",
            "audio": "/top-100-music",
            "games": "/top-100-games",
            "apps": "/top-100-applications",
            None: "/top-100",
        }
        path = category_paths.get(category, category_paths[None])
        url = f"{self.base_url}{path}"

        try:
            html_text = self._fetch(url)

            if "just a moment" in html_text.lower() or "cf-chl" in html_text.lower():
                raise RuntimeError("1337x blocked by Cloudflare")

            partial_results = self._parse_search_results(html_text)[:10]

            results: list[TorrentResult] = []
            for item in partial_results:
                magnet = self._get_magnet_from_detail_page(item["detail_url"])
                if magnet:
                    results.append(
                        TorrentResult(
                            name=item["name"],
                            magnet=magnet,
                            seeders=item["seeders"],
                            leechers=item["leechers"],
                            source=self.name,
                        )
                    )

            if results:
                logger.debug("1337x top results: %s", len(results))
                return results

        except Exception as exc:
            logger.debug("1337x top failed: %s", exc)
            if debug_sink:
                debug_sink("1337x top failed", str(exc))

        return []


class LimeTorrentsSource(TorrentSource):
    """LimeTorrents torrent source.

    Uses cloudscraper to bypass Cloudflare protection.
    """

    name = "LimeTorrents"
    enabled = CLOUDSCRAPER_AVAILABLE
    base_url = os.environ.get("LIMETORRENTS_BASE_URL", "https://www.limetorrents.lol")

    # Regex patterns for parsing
    _ROW_RE = re.compile(
        r'<tr[^>]*class="[^"]*"[^>]*>(.*?)</tr>',
        re.IGNORECASE | re.DOTALL,
    )
    _NAME_LINK_RE = re.compile(
        r'<a href="([^"]+)"[^>]*class="[^"]*coll-1[^"]*"[^>]*>([^<]+)</a>',
        re.IGNORECASE,
    )
    _SEEDS_RE = re.compile(
        r'<td class="[^"]*tdseed[^"]*">(\d+)</td>',
        re.IGNORECASE,
    )
    _LEECHES_RE = re.compile(
        r'<td class="[^"]*tdleech[^"]*">(\d+)</td>',
        re.IGNORECASE,
    )
    _HASH_RE = re.compile(r"/([a-fA-F0-9]{40})\.torrent", re.IGNORECASE)

    def _fetch(self, url: str) -> str:
        """Fetch HTML using cloudscraper to bypass Cloudflare."""
        html_text = _fetch_with_cloudscraper(
            url, referer=self.base_url, timeout=self.timeout
        )
        if html_text:
            return html_text

        headers = _build_browser_headers(self.base_url)
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def _parse_results(self, html_text: str) -> list[TorrentResult]:
        """Parse search/top results from HTML."""
        results: list[TorrentResult] = []

        # Find table rows with torrent info
        for row in self._ROW_RE.findall(html_text):
            name_match = self._NAME_LINK_RE.search(row)
            seeds_match = self._SEEDS_RE.search(row)
            leeches_match = self._LEECHES_RE.search(row)

            if not name_match:
                continue

            name = html.unescape(name_match.group(2).strip())

            # Extract info hash from torrent link
            hash_match = self._HASH_RE.search(row)
            if not hash_match:
                continue

            info_hash = hash_match.group(1).upper()

            try:
                seeders = int(seeds_match.group(1)) if seeds_match else 0
                leechers = int(leeches_match.group(1)) if leeches_match else 0
            except ValueError:
                seeders = 0
                leechers = 0

            magnet = _build_magnet(info_hash, name)
            results.append(
                TorrentResult(
                    name=name,
                    magnet=magnet,
                    seeders=seeders,
                    leechers=leechers,
                    source=self.name,
                )
            )

        return results

    def search(
        self, query: str, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Search LimeTorrents."""
        if not self.enabled:
            return []

        q = (query or "").strip()
        if not q:
            return []

        url = f"{self.base_url}/search/all/{quote(q)}/"

        try:
            html_text = self._fetch(url)

            if "just a moment" in html_text.lower() or "cf-chl" in html_text.lower():
                raise RuntimeError("LimeTorrents blocked by Cloudflare")

            results = self._parse_results(html_text)
            results = sorted(results, key=lambda r: r.seeders, reverse=True)[:10]

            if results:
                logger.debug("limetorrents search results: %s", len(results))
                return results

        except Exception as exc:
            logger.debug("limetorrents search failed: %s", exc)
            if debug_sink:
                debug_sink("limetorrents search failed", str(exc))

        return []

    def top(
        self, category: str | None = None, debug_sink: Callable | None = None
    ) -> list[TorrentResult]:
        """Get top torrents from LimeTorrents."""
        if not self.enabled:
            return []

        # LimeTorrents category paths
        category_paths = {
            "movies": "/browse-torrents/Movies/",
            "video": "/browse-torrents/Movies/",
            "tv": "/browse-torrents/TV-shows/",
            "hdtv": "/browse-torrents/TV-shows/",
            "music": "/browse-torrents/Music/",
            "audio": "/browse-torrents/Music/",
            "games": "/browse-torrents/Games/",
            "apps": "/browse-torrents/Applications/",
            "anime": "/browse-torrents/Anime/",
            None: "/top100",
        }
        path = category_paths.get(category, category_paths[None])
        url = f"{self.base_url}{path}"

        try:
            html_text = self._fetch(url)

            if "just a moment" in html_text.lower() or "cf-chl" in html_text.lower():
                raise RuntimeError("LimeTorrents blocked by Cloudflare")

            results = self._parse_results(html_text)
            results = sorted(results, key=lambda r: r.seeders, reverse=True)[:10]

            if results:
                logger.debug("limetorrents top results: %s", len(results))
                return results

        except Exception as exc:
            logger.debug("limetorrents top failed: %s", exc)
            if debug_sink:
                debug_sink("limetorrents top failed", str(exc))

        return []


# Registry of all available sources in priority order
SOURCES: list[TorrentSource] = [
    BitSearchSource(),
    EZTVSource(),
    X1337Source(),
    LimeTorrentsSource(),
]


def get_enabled_sources() -> list[TorrentSource]:
    """Get list of enabled torrent sources."""
    return [s for s in SOURCES if s.enabled]


def fallback_search(
    query: str, debug_sink: Callable | None = None
) -> list[TorrentResult]:
    """Search across all fallback sources until results are found."""
    for source in get_enabled_sources():
        try:
            results = source.search(query, debug_sink)
            if results:
                logger.info(
                    "fallback search found %d results from %s",
                    len(results),
                    source.name,
                )
                return results
        except Exception as exc:
            logger.debug("fallback source %s failed: %s", source.name, exc)
            if debug_sink:
                debug_sink(f"fallback {source.name} failed", str(exc))
            continue

    return []


def fallback_top(
    category: str | None = None, debug_sink: Callable | None = None
) -> list[TorrentResult]:
    """Get top torrents from fallback sources."""
    for source in get_enabled_sources():
        try:
            results = source.top(category, debug_sink)
            if results:
                logger.info(
                    "fallback top found %d results from %s",
                    len(results),
                    source.name,
                )
                return results
        except Exception as exc:
            logger.debug("fallback source %s failed: %s", source.name, exc)
            if debug_sink:
                debug_sink(f"fallback {source.name} failed", str(exc))
            continue

    return []

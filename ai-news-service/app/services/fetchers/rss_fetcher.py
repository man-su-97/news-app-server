"""
app/services/fetchers/rss_fetcher.py — RSS Feed Fetcher
========================================================
Fetches and parses RSS/Atom XML feeds from a URL.

RSS (Really Simple Syndication) is an XML format used by news websites to
publish their articles as a machine-readable feed. Example RSS URL:
  https://timesofindia.indiatimes.com/rss.cms

This fetcher uses the `feedparser` library which handles:
  - XML parsing (both RSS 2.0 and Atom formats)
  - Date parsing from various RSS date formats
  - Malformed XML (with the "bozo" error flag)
  - Media extensions (images, thumbnails)

Architecture decision: feedparser.parse() is synchronous (blocking IO).
We wrap it in asyncio.to_thread() so it runs in a thread pool and doesn't
block the async event loop while waiting for the network request to complete.
Without this, one slow RSS feed would freeze ALL requests to the server.
"""

import asyncio   # For asyncio.to_thread — runs blocking code in a thread pool
import logging

import feedparser  # Third-party library for parsing RSS/Atom feeds

logger = logging.getLogger(__name__)


class RSSFetcher:
    """Fetches and parses a single RSS feed URL."""

    async def fetch(self, url: str):
        """Fetch an RSS feed and return the parsed feedparser result.

        Returns a feedparser Feed object. The important attribute is:
          feed.entries — list of FeedParserDict, one per article

        Raises RuntimeError if the HTTP request itself fails (not just malformed XML).
        Malformed XML is logged as a warning but does NOT raise — feedparser
        does its best to parse whatever it gets.
        """
        try:
            # asyncio.to_thread() runs feedparser.parse() in a thread pool.
            # feedparser makes a blocking HTTP request + XML parse — both are slow.
            # Running in a thread means other async tasks can proceed concurrently.
            feed = await asyncio.to_thread(feedparser.parse, url)
        except Exception as exc:
            # The fetch itself failed (DNS error, timeout, connection refused, etc.)
            logger.error("RSS fetch failed for %s: %s", url, exc)
            raise RuntimeError(f"Failed to fetch RSS feed: {url}") from exc

        # feedparser sets feed.bozo=True if the XML was malformed/invalid.
        # We log a warning but continue — feedparser often extracts articles
        # from malformed feeds. Raising here would drop valid articles.
        if feed.bozo and feed.bozo_exception:
            logger.warning(
                "Malformed RSS at %s (bozo flag set): %s", url, feed.bozo_exception
            )

        # If the feed parsed but has no articles, log it (not an error —
        # the feed might just be empty right now).
        if not feed.entries:
            logger.warning("No entries found in RSS feed: %s", url)

        # Return the full feedparser result — the caller accesses feed.entries
        return feed

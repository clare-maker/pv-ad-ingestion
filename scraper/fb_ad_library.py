"""
FB Ad Library Playwright scraper.
Loads a public FB Ad Library page, scrolls to load ads, and parses ad cards.

This is the highest-risk module — FB's DOM changes frequently.
Built with defensive parsing using known text patterns from the
FB Ad Library page structure (as of March 2026).
"""

import re
import time
import logging
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from scraper.normalizer import normalize_ad

logger = logging.getLogger(__name__)


def extract_page_id(url):
    """Pull view_all_page_id from a FB Ad Library URL."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        ids = params.get("view_all_page_id", [])
        return ids[0] if ids else None
    except Exception:
        return None


def scrape_fb_ad_library(url, config, progress_callback=None):
    """Scrape ads from FB Ad Library.

    Args:
        url: FB Ad Library URL (must contain view_all_page_id param)
        config: Dict from config.yaml with scraper settings
        progress_callback: Optional callable(status_text, pct) for Streamlit progress

    Returns:
        Dict with keys:
            ads: List of normalized ad dicts
            total_found: How many ad cards were detected
            successfully_parsed: How many were parsed into schema
            parse_failures: Count of cards that failed parsing
            source_url: The original URL
    """
    scraper_config = config.get("scraper", {})
    max_ads = scraper_config.get("max_ads", 75)
    scroll_delay = scraper_config.get("scroll_delay_seconds", 1.5)
    timeout_ms = scraper_config.get("page_load_timeout_seconds", 30) * 1000
    vw = scraper_config.get("viewport_width", 1280)
    vh = scraper_config.get("viewport_height", 900)

    # Use the URL as-is — preserve user's filters
    library_url = url.strip()

    if progress_callback:
        progress_callback("Launching browser...", 0.05)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": vw, "height": vh},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # --- Load the page with retries ---
        loaded = False
        for attempt in range(3):
            try:
                if progress_callback:
                    progress_callback(f"Loading page (attempt {attempt + 1})...", 0.10)
                page.goto(library_url, timeout=timeout_ms, wait_until="networkidle")
                loaded = True
                break
            except Exception as e:
                logger.warning(f"Page load attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    time.sleep(5)
        if not loaded:
            browser.close()
            return {
                "ads": [],
                "total_found": 0,
                "successfully_parsed": 0,
                "parse_failures": 0,
                "source_url": url,
                "error": "Failed to load FB Ad Library page after 3 attempts",
            }

        # --- Wait for ad content to appear ---
        if progress_callback:
            progress_callback("Waiting for ads to load...", 0.15)
        time.sleep(3)

        # --- Scroll to load more ads ---
        if progress_callback:
            progress_callback("Scrolling to load ads...", 0.20)

        prev_count = 0
        stale_scrolls = 0

        while True:
            current_count = _count_ad_cards(page)

            if progress_callback:
                pct = min(0.20 + (current_count / max_ads) * 0.50, 0.70)
                progress_callback(f"Found {current_count} ads (scrolling...)", pct)

            if current_count >= max_ads:
                logger.info(f"Hit max_ads cap ({max_ads}), stopping scroll")
                break
            if current_count == prev_count:
                stale_scrolls += 1
                if stale_scrolls >= 3:
                    logger.info("No new ads after 3 scrolls, pagination complete")
                    break
            else:
                stale_scrolls = 0

            prev_count = current_count
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(scroll_delay)

            try:
                see_more = page.query_selector('text="See more results"')
                if see_more:
                    see_more.click()
                    time.sleep(scroll_delay)
            except Exception:
                pass

        # --- Extract full page text and parse ---
        if progress_callback:
            progress_callback("Parsing ad data...", 0.75)

        all_text = page.inner_text("body")
        raw_ads = _parse_ads_from_text(all_text)

        if progress_callback:
            progress_callback("Done!", 1.0)

        browser.close()

    # Normalize each raw ad
    normalized = []
    failures = 0
    for i, raw in enumerate(raw_ads):
        try:
            ad = normalize_ad(raw)
            ad["source_url"] = url
            ad["frequency_count"] = i + 1
            normalized.append(ad)
        except Exception as e:
            logger.warning(f"Failed to normalize ad {i}: {e}")
            failures += 1

    return {
        "ads": normalized,
        "total_found": len(raw_ads),
        "successfully_parsed": len(normalized),
        "parse_failures": failures,
        "source_url": url,
    }


def _count_ad_cards(page):
    """Count ad cards on page by counting 'Library ID:' occurrences."""
    try:
        return page.locator('text=/Library ID:/').count()
    except Exception:
        return 0


def _parse_ads_from_text(all_text):
    """Parse ads from the full page text.

    FB Ad Library renders each ad as continuous text (no newlines) like:
        Library ID: 123456
        Started running on Feb 11, 2026Platforms...EU transparency...See ad details
        James WalkerSponsored • Paid for by Company and others
        {primary_text}{DOMAIN.COM}{headline}{description}Learn more

    We split on "Library ID:" boundaries, then use regex anchors to extract
    the actual ad creative fields from each chunk.
    """
    ads = []

    # Split on Library ID boundaries
    chunks = re.split(r'Library ID:\s*\d+', all_text)

    # Skip the first chunk (page header before any ads)
    ad_chunks = chunks[1:] if len(chunks) > 1 else []

    for idx, chunk in enumerate(ad_chunks):
        try:
            ad = _parse_single_ad(chunk)
            if ad:
                ads.append(ad)
        except Exception as e:
            logger.debug(f"Failed to parse ad chunk {idx}: {e}")
            continue

    logger.info(f"Parsed {len(ads)} ads from {len(ad_chunks)} chunks")
    return ads


def _parse_single_ad(chunk):
    """Parse a single ad from its text chunk.

    The text is continuous (no line breaks). Key anchors:
    1. "Started running on {date}" — extract the date
    2. "Sponsored • Paid for by...others" or just "Sponsored" — marks end of metadata
    3. Domain pattern like "SMARTDEALSEARCH.COM" — separates primary_text from headline
    4. "Learn more" / "Sign up" / "Shop now" — marks end of ad creative
    """
    # Strip zero-width spaces
    chunk = chunk.replace('\u200b', '')

    # 1. Extract the date
    date_match = re.search(r'Started running on ([A-Za-z]+ \d{1,2}, \d{4})', chunk)
    start_date = date_match.group(1) if date_match else ""

    # 2. Find "Sponsored" anchor — everything after this is ad creative
    # Pattern: "Sponsored • Paid for by {company} and others" or just "Sponsored"
    sponsored_match = re.search(
        r'Sponsored\s*[•·]\s*Paid for by .+?(?:and others|\.)',
        chunk
    )
    if not sponsored_match:
        # Fallback: just look for "Sponsored"
        sponsored_match = re.search(r'Sponsored', chunk)
    if not sponsored_match:
        return None

    # Everything after "Sponsored..." is the ad creative
    creative_text = chunk[sponsored_match.end():]

    # 3. Find the CTA at the end to trim — "Learn more", "Sign up", "Shop now", etc.
    # Also trim trailing "Active" or "Inactive" status
    cta_pattern = r'(Learn more|Sign up|Shop now|Apply now|Get offer|See more|Download|Book now|Contact us|Watch more|Send message|Subscribe|Get quote|Listen now).*$'
    creative_text = re.split(cta_pattern, creative_text)[0]

    # 4. Find the domain line (ALL-CAPS with explicit TLD — stops before the headline starts)
    # FB concatenates like "SMARTDEALSEARCH.COMConstruction Worker..." so we need exact TLD match
    tlds = r'(?:COM|NET|ORG|CO|IO|INFO|BIZ|US|UK|DE|FR|ES|IT|NL|CA|AU|EDU|GOV|APP|DEV|XYZ|SITE|ONLINE|STORE|SHOP|PRO|ME|TV)'
    domain_match = re.search(rf'([A-Z0-9][A-Z0-9\-]+\.{tlds})', creative_text)

    primary_text = ""
    headline = ""
    link = ""

    if domain_match:
        link = domain_match.group(1).lower()
        # Primary text = everything before the domain
        primary_text = creative_text[:domain_match.start()].strip()
        # Headline = everything after the domain
        headline = creative_text[domain_match.end():].strip()
    else:
        # No domain found — treat the whole creative as primary text
        primary_text = creative_text.strip()

    # Skip ads with no useful content
    if not primary_text and not headline:
        return None

    # Clean up — remove leading/trailing punctuation artifacts
    primary_text = primary_text.strip()
    headline = headline.strip()

    return {
        "headline": headline[:200],
        "primary_text": primary_text[:500],
        "link": f"https://{link}" if link else "",
        "start_date": start_date,
        "media_type": "image",
    }

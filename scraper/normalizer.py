"""
Normalizes raw scraped or CSV ad data into the spec's normalized ad schema.
"""

import re
from datetime import datetime
from urllib.parse import urlparse


def calculate_days_active(start_date_str):
    """Calculate days active from a date string like 'Mar 1, 2026' or 'Started running on Mar 1, 2026'.

    Returns int days active, or 0 if parsing fails.
    """
    if not start_date_str:
        return 0

    # Strip common prefix from FB Ad Library
    cleaned = re.sub(r"^Started running on\s*", "", str(start_date_str).strip())

    # Try common date formats
    formats = ["%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y"]
    for fmt in formats:
        try:
            start = datetime.strptime(cleaned, fmt)
            days = (datetime.now() - start).days
            return max(days, 0)
        except ValueError:
            continue
    return 0


def extract_domain(url):
    """Extract the domain from a URL string. Returns empty string on failure."""
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.replace("www.", "")
    except Exception:
        return ""


def normalize_ad(raw_ad):
    """Convert a raw scraped/CSV ad dict into the spec's normalized schema.

    Args:
        raw_ad: Dict with keys like headline, body/primary_text, link/url,
                start_date, media_type, etc. Flexible key matching.

    Returns:
        Dict matching the normalized ad schema.
    """
    # Flexible key matching — try multiple possible field names
    headline = (
        raw_ad.get("headline")
        or raw_ad.get("title")
        or raw_ad.get("ad_headline")
        or ""
    )

    primary_text = (
        raw_ad.get("primary_text")
        or raw_ad.get("body")
        or raw_ad.get("body_text")
        or raw_ad.get("ad_body")
        or raw_ad.get("description")
        or ""
    )

    link = (
        raw_ad.get("link")
        or raw_ad.get("url")
        or raw_ad.get("destination_url")
        or raw_ad.get("landing_page")
        or ""
    )

    start_date = (
        raw_ad.get("start_date")
        or raw_ad.get("started_running")
        or raw_ad.get("date")
        or raw_ad.get("created_date")
        or ""
    )

    media_type = (
        raw_ad.get("media_type")
        or raw_ad.get("ad_type")
        or raw_ad.get("format")
        or "image"
    )
    # Normalize media_type to allowed values
    media_type_lower = str(media_type).lower()
    if "video" in media_type_lower:
        media_type = "video"
    elif "carousel" in media_type_lower:
        media_type = "carousel"
    else:
        media_type = "image"

    source_url = raw_ad.get("source_url", "")

    return {
        "topic": "",                                    # Filled by clustering
        "offer_type": "",                               # Filled by clustering
        "headline": str(headline).strip(),
        "primary_text": str(primary_text).strip(),
        "banner_text": "",                              # Populated in copy gen
        "destination_domain": extract_domain(link),
        "funnel_type": "",                              # Filled by clustering
        "run_duration_signal": calculate_days_active(start_date),
        "frequency_count": 0,                           # Proxy set by caller
        "source_url": str(source_url).strip(),
        "media_type": media_type,
    }

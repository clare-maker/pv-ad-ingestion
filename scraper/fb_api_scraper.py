"""
FB Ad Library API scraper — replaces the Playwright browser scraper.

Uses Meta's /ads_archive Graph API endpoint to fetch ad creative data.
Works on Streamlit Cloud (no browser needed, just HTTP requests).

Requires META_ACCESS_TOKEN with ads_read permission.
"""

import os
import json
import logging
import requests
from urllib.parse import urlparse, parse_qs
from scraper.normalizer import normalize_ad

logger = logging.getLogger(__name__)

BASE_URL = "https://graph.facebook.com"

# Fields we request from the Ad Library API
AD_FIELDS = ",".join([
    "id",
    "page_id",
    "page_name",
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_captions",
    "ad_creative_link_descriptions",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_snapshot_url",
    "publisher_platforms",
])


def _get_token():
    """Get Meta access token from environment or Streamlit secrets."""
    token = os.environ.get("META_ACCESS_TOKEN", "")

    if not token:
        try:
            import streamlit as st
            token = st.secrets.get("META_ACCESS_TOKEN", "")
        except Exception:
            pass

    if not token:
        raise ValueError(
            "META_ACCESS_TOKEN not set. Add it to .env (local) or Streamlit secrets (cloud)."
        )
    return token


def extract_page_id(url):
    """Pull view_all_page_id from a FB Ad Library URL."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        ids = params.get("view_all_page_id", [])
        return ids[0] if ids else None
    except Exception:
        return None


def extract_search_terms(url):
    """Pull search_terms (q parameter) from a FB Ad Library URL."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        terms = params.get("q", [])
        return terms[0] if terms else None
    except Exception:
        return None


def scrape_fb_ad_library(url, config, progress_callback=None):
    """Fetch ads from Meta's Ad Library API.

    Accepts the same FB Ad Library URL the user pastes in the UI.
    Extracts page_id or search_terms from the URL and queries the API.

    Args:
        url: FB Ad Library URL (with view_all_page_id or q param)
        config: Dict from config.yaml with scraper settings
        progress_callback: Optional callable(status_text, pct) for progress

    Returns:
        Dict with keys:
            ads: List of normalized ad dicts
            total_found: How many ads the API returned
            successfully_parsed: How many were normalized
            parse_failures: Count that failed normalization
            source_url: The original URL
    """
    scraper_config = config.get("scraper", {})
    max_ads = scraper_config.get("max_ads", 75)
    meta_config = config.get("meta", {})
    api_version = meta_config.get("api_version", "v25.0")
    countries = meta_config.get("default_countries", ["US"])

    if progress_callback:
        progress_callback("Connecting to Meta Ad Library API...", 0.05)

    token = _get_token()

    # Extract page_id or search_terms from the URL
    page_id = extract_page_id(url)
    search_terms = extract_search_terms(url)

    if not page_id and not search_terms:
        return {
            "ads": [],
            "total_found": 0,
            "successfully_parsed": 0,
            "parse_failures": 0,
            "source_url": url,
            "error": (
                "Could not extract page ID or search terms from URL. "
                "Make sure the URL contains view_all_page_id=... or q=... parameter."
            ),
        }

    # Build API request
    api_url = f"{BASE_URL}/{api_version}/ads_archive"
    params = {
        "access_token": token,
        "fields": AD_FIELDS,
        "ad_reached_countries": json.dumps(countries),
        "ad_active_status": "ALL",
        "limit": min(max_ads, 100),  # API max per page is ~100
    }

    if page_id:
        params["search_page_ids"] = page_id
        logger.info(f"Searching Ad Library for page ID: {page_id}")
    else:
        params["search_terms"] = search_terms
        logger.info(f"Searching Ad Library for terms: {search_terms}")

    if progress_callback:
        progress_callback("Fetching ads from API...", 0.20)

    # Fetch pages of results until we hit max_ads
    all_raw_ads = []
    page_num = 0

    while len(all_raw_ads) < max_ads:
        page_num += 1
        try:
            resp = requests.get(api_url, params=params, timeout=30)
            result = resp.json()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            if not all_raw_ads:
                return {
                    "ads": [],
                    "total_found": 0,
                    "successfully_parsed": 0,
                    "parse_failures": 0,
                    "source_url": url,
                    "error": f"Meta API request failed: {e}",
                }
            break

        # Check for API error
        if "error" in result:
            err = result["error"]
            error_msg = err.get("error_user_msg") or err.get("message", "Unknown error")
            logger.error(f"Meta Ad Library API error: {error_msg}")
            if not all_raw_ads:
                return {
                    "ads": [],
                    "total_found": 0,
                    "successfully_parsed": 0,
                    "parse_failures": 0,
                    "source_url": url,
                    "error": f"Meta Ad Library API: {error_msg}",
                }
            break

        ads_data = result.get("data", [])
        if not ads_data:
            break

        all_raw_ads.extend(ads_data)

        if progress_callback:
            pct = min(0.20 + (len(all_raw_ads) / max_ads) * 0.55, 0.75)
            progress_callback(f"Fetched {len(all_raw_ads)} ads...", pct)

        # Check for next page
        paging = result.get("paging", {})
        next_url = paging.get("next")
        if not next_url or len(all_raw_ads) >= max_ads:
            break

        # Use the full next URL for pagination (it includes the cursor)
        api_url = next_url
        params = {}  # next_url already has all params

    # Trim to max_ads
    all_raw_ads = all_raw_ads[:max_ads]

    if progress_callback:
        progress_callback("Normalizing ad data...", 0.80)

    # Convert API response to our normalized format
    normalized = []
    failures = 0
    for i, api_ad in enumerate(all_raw_ads):
        try:
            raw = _api_ad_to_raw(api_ad)
            ad = normalize_ad(raw)
            ad["source_url"] = url
            ad["frequency_count"] = i + 1
            normalized.append(ad)
        except Exception as e:
            logger.warning(f"Failed to normalize ad {i}: {e}")
            failures += 1

    if progress_callback:
        progress_callback("Done!", 1.0)

    logger.info(f"Fetched {len(all_raw_ads)} ads from API, normalized {len(normalized)}")

    return {
        "ads": normalized,
        "total_found": len(all_raw_ads),
        "successfully_parsed": len(normalized),
        "parse_failures": failures,
        "source_url": url,
    }


def _api_ad_to_raw(api_ad):
    """Convert a Meta Ad Library API response dict to our raw ad format.

    The API returns arrays for creative fields (to handle carousel/multi-creative ads).
    We take the first element of each array.
    """
    # ad_creative_bodies is a list — primary text
    bodies = api_ad.get("ad_creative_bodies", [])
    primary_text = bodies[0] if bodies else ""

    # ad_creative_link_titles is a list — headline
    titles = api_ad.get("ad_creative_link_titles", [])
    headline = titles[0] if titles else ""

    # ad_creative_link_captions is a list — often the display URL/domain
    captions = api_ad.get("ad_creative_link_captions", [])
    link = captions[0] if captions else ""

    # ad_creative_link_descriptions — secondary text below headline
    descriptions = api_ad.get("ad_creative_link_descriptions", [])
    description = descriptions[0] if descriptions else ""

    # Start date
    start_date = api_ad.get("ad_delivery_start_time", "")

    return {
        "headline": headline,
        "primary_text": primary_text,
        "description": description,
        "link": link,
        "start_date": start_date,
        "media_type": "image",
    }

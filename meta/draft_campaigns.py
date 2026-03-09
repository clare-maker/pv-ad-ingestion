"""
Meta Marketing API — draft PAUSED campaigns, ad sets, and ads.

Structure per run:
  1 campaign per topic → 1 ad set per angle → 4 ads per ad set
  (2 text variants × 2 banner images = 4 creative combos)

All objects are created PAUSED. Uses the Meta Graph API via requests.
"""

import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://graph.facebook.com"


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


def _api_url(config, path):
    """Build API URL from config."""
    version = config.get("meta", {}).get("api_version", "v25.0")
    return f"{BASE_URL}/{version}/{path}"


def _post(url, data, token):
    """Make a POST request to Meta API, return response JSON or raise."""
    data["access_token"] = token
    resp = requests.post(url, data=data, timeout=30)
    result = resp.json()
    if "error" in result:
        err = result["error"]
        raise RuntimeError(
            f"Meta API error: {err.get('error_user_msg') or err.get('message', 'Unknown error')}"
        )
    return result


def _post_multipart(url, data, files, token):
    """POST with multipart file upload (for ad images)."""
    data["access_token"] = token
    resp = requests.post(url, data=data, files=files, timeout=60)
    result = resp.json()
    if "error" in result:
        err = result["error"]
        raise RuntimeError(
            f"Meta API error: {err.get('error_user_msg') or err.get('message', 'Unknown error')}"
        )
    return result


# ── Campaign ──────────────────────────────────────────────

def create_draft_campaign(topic_name, campaign_name, config):
    """Create a single PAUSED campaign for a topic."""
    token = _get_token()
    meta_config = config.get("meta", {})
    ad_account = meta_config.get("ad_account_id", "")
    objective = meta_config.get("objective", "OUTCOME_LEADS")

    if not ad_account:
        raise ValueError("meta.ad_account_id not set in config.yaml")

    url = _api_url(config, f"{ad_account}/campaigns")
    data = {
        "name": campaign_name,
        "objective": objective,
        "status": "PAUSED",
        "special_ad_categories": "[]",
        "is_adset_budget_sharing_enabled": "false",
    }

    result = _post(url, data, token)
    campaign_id = result["id"]
    logger.info(f"Created PAUSED campaign '{campaign_name}' (ID: {campaign_id})")
    return {"campaign_id": campaign_id, "name": campaign_name}


# ── Ad Set ────────────────────────────────────────────────

def create_draft_adset(campaign_id, angle_name, adset_name, config):
    """Create a single PAUSED ad set under a campaign."""
    token = _get_token()
    meta_config = config.get("meta", {})
    ad_account = meta_config.get("ad_account_id", "")
    daily_budget = meta_config.get("default_daily_budget", 2000)
    countries = meta_config.get("default_countries", ["US"])

    if not ad_account:
        raise ValueError("meta.ad_account_id not set in config.yaml")

    targeting = json.dumps({
        "geo_locations": {"countries": countries},
        "age_min": 18,
        "age_max": 65,
    })

    url = _api_url(config, f"{ad_account}/adsets")
    data = {
        "name": adset_name,
        "campaign_id": campaign_id,
        "status": "PAUSED",
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "LEAD_GENERATION",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "daily_budget": str(daily_budget),
        "targeting": targeting,
    }

    result = _post(url, data, token)
    adset_id = result["id"]
    logger.info(f"Created PAUSED ad set '{adset_name}' (ID: {adset_id})")
    return {"adset_id": adset_id, "name": adset_name}


# ── Image Upload ──────────────────────────────────────────

def upload_ad_image(image_path, config):
    """Upload a banner image to the ad account and return its image_hash.

    Args:
        image_path: Local file path to the PNG/JPG image
        config: Dict from config.yaml

    Returns:
        image_hash string
    """
    token = _get_token()
    meta_config = config.get("meta", {})
    ad_account = meta_config.get("ad_account_id", "")

    url = _api_url(config, f"{ad_account}/adimages")

    with open(image_path, "rb") as f:
        result = _post_multipart(
            url,
            data={},
            files={"filename": (os.path.basename(image_path), f, "image/png")},
            token=token,
        )

    # Response: {"images": {"filename": {"hash": "abc123", ...}}}
    images = result.get("images", {})
    for img_data in images.values():
        image_hash = img_data.get("hash")
        if image_hash:
            logger.info(f"Uploaded image '{image_path}' → hash: {image_hash}")
            return image_hash

    raise RuntimeError(f"No image_hash returned for {image_path}: {result}")


# ── Ad Creative ───────────────────────────────────────────

def create_ad_creative(ad_name, headline, primary_text, image_hash, config):
    """Create an ad creative combining text + image.

    Args:
        ad_name: Name for this creative
        headline: Headline text
        primary_text: Body / primary text
        image_hash: From upload_ad_image()
        config: Dict from config.yaml

    Returns:
        creative_id string
    """
    token = _get_token()
    meta_config = config.get("meta", {})
    ad_account = meta_config.get("ad_account_id", "")
    page_id = meta_config.get("page_id", "")
    destination_url = meta_config.get("destination_url", "")

    if not page_id:
        raise ValueError("meta.page_id not set in config.yaml")
    if not destination_url:
        raise ValueError("meta.destination_url not set in config.yaml")

    # Build the object_story_spec — this is the actual ad content
    object_story_spec = json.dumps({
        "page_id": page_id,
        "link_data": {
            "image_hash": image_hash,
            "link": destination_url,
            "message": primary_text,
            "name": headline,
            "call_to_action": {
                "type": "LEARN_MORE",
                "value": {"link": destination_url},
            },
        },
    })

    url = _api_url(config, f"{ad_account}/adcreatives")
    data = {
        "name": ad_name,
        "object_story_spec": object_story_spec,
    }

    result = _post(url, data, token)
    creative_id = result["id"]
    logger.info(f"Created ad creative '{ad_name}' (ID: {creative_id})")
    return creative_id


# ── Ad ────────────────────────────────────────────────────

def create_ad(adset_id, creative_id, ad_name, config):
    """Create a PAUSED ad linking a creative to an ad set.

    Args:
        adset_id: Ad set ID to place this ad in
        creative_id: Creative ID from create_ad_creative()
        ad_name: Display name for the ad
        config: Dict from config.yaml

    Returns:
        Dict with ad_id and name
    """
    token = _get_token()
    meta_config = config.get("meta", {})
    ad_account = meta_config.get("ad_account_id", "")

    url = _api_url(config, f"{ad_account}/ads")
    data = {
        "name": ad_name,
        "adset_id": adset_id,
        "creative": json.dumps({"creative_id": creative_id}),
        "status": "PAUSED",
    }

    result = _post(url, data, token)
    ad_id = result["id"]
    logger.info(f"Created PAUSED ad '{ad_name}' (ID: {ad_id})")
    return {"ad_id": ad_id, "name": ad_name}


# ── Orchestrator ──────────────────────────────────────────

def draft_run_to_meta(run_data, config):
    """Draft an entire run to Meta as PAUSED campaigns + ad sets + ads.

    Structure:
      1 campaign per topic
        → 1 ad set per angle
          → 4 ads per ad set (2 text variants × 2 banner images)

    Args:
        run_data: Dict from asset_library.json
        config: Dict from config.yaml

    Returns:
        Dict with campaigns, total_campaigns, total_adsets, total_ads
    """
    creatives = run_data.get("creatives", [])
    if not creatives:
        raise ValueError("No creatives in this run to draft.")

    # Group creatives by topic
    topics = {}
    for creative in creatives:
        topic_slug = creative.get("topic_slug", "unknown")
        if topic_slug not in topics:
            topics[topic_slug] = {
                "topic_name": creative.get("topic", "Unknown"),
                "topic_slug": topic_slug,
                "angles": [],
            }
        topics[topic_slug]["angles"].append(creative)

    # Build run identifier for naming
    from datetime import datetime
    ts_raw = run_data.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts_raw)
        date_str = dt.strftime("%Y%m%d")
    except (ValueError, TypeError):
        date_str = datetime.now().strftime("%Y%m%d")

    domain = run_data.get("pv_domain", "").replace(".", "-") or "pv"
    buyer = run_data.get("buyer_initials", "xx")

    results = []
    total_adsets = 0
    total_ads = 0

    for topic_slug, topic_data in topics.items():
        # Campaign name: {topic_slug}_{domain}_{buyer}_{date}
        campaign_name = f"{topic_slug}_{domain}_{buyer}_{date_str}"

        campaign = create_draft_campaign(
            topic_name=topic_data["topic_name"],
            campaign_name=campaign_name,
            config=config,
        )

        adsets = []
        for creative in topic_data["angles"]:
            angle_slug = creative.get("angle_slug", "unknown")
            variants = creative.get("variants", [])
            n_vars = len(variants)
            adset_name = f"{angle_slug}_{n_vars}vars"

            adset = create_draft_adset(
                campaign_id=campaign["campaign_id"],
                angle_name=creative.get("angle", "Unknown"),
                adset_name=adset_name,
                config=config,
            )
            total_adsets += 1

            # ── Create 4 ads: 2 text variants × 2 banner images ──
            # Collect all banner images from variants
            image_hashes = []
            for v in variants:
                banner_path = v.get("banner_path", "")
                if banner_path and os.path.isfile(banner_path):
                    try:
                        img_hash = upload_ad_image(banner_path, config)
                        image_hashes.append(img_hash)
                    except Exception as e:
                        logger.warning(f"Failed to upload banner {banner_path}: {e}")

            # Create ads — cross every text variant with every image
            ads_created = []
            for v_idx, v in enumerate(variants, 1):
                v_style = v.get("variant_type", "unknown").lower()
                headline = v.get("headline", "")
                primary_text = v.get("primary_text", "")

                if not headline and not primary_text:
                    continue

                for img_idx, img_hash in enumerate(image_hashes, 1):
                    ad_name = f"{angle_slug}_v{v_idx}-{v_style}_img{img_idx}"
                    try:
                        creative_id = create_ad_creative(
                            ad_name=ad_name,
                            headline=headline,
                            primary_text=primary_text,
                            image_hash=img_hash,
                            config=config,
                        )
                        ad = create_ad(
                            adset_id=adset["adset_id"],
                            creative_id=creative_id,
                            ad_name=ad_name,
                            config=config,
                        )
                        ads_created.append(ad)
                        total_ads += 1
                    except Exception as e:
                        logger.warning(f"Failed to create ad '{ad_name}': {e}")

            adset["ads"] = ads_created
            adsets.append(adset)

        campaign["adsets"] = adsets
        results.append(campaign)

    logger.info(
        f"Drafted {len(results)} campaigns, {total_adsets} ad sets, "
        f"{total_ads} ads to Meta (PAUSED)"
    )

    return {
        "campaigns": results,
        "total_campaigns": len(results),
        "total_adsets": total_adsets,
        "total_ads": total_ads,
    }

"""
Meta Marketing API — draft PAUSED campaigns + ad sets.

Creates one PAUSED campaign per topic, one PAUSED ad set per angle.
No ads are created (requires a Facebook Page to be assigned later).

Uses the Meta Graph API via requests (no SDK dependency).
"""

import os
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


def create_draft_campaign(topic_name, campaign_name, config):
    """Create a single PAUSED campaign for a topic.

    Args:
        topic_name: Human-readable topic name (for logging)
        campaign_name: Campaign name string
        config: Dict from config.yaml

    Returns:
        Dict with campaign_id and name
    """
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


def create_draft_adset(campaign_id, angle_name, adset_name, config):
    """Create a single PAUSED ad set under a campaign.

    Args:
        campaign_id: Meta campaign ID from create_draft_campaign
        angle_name: Human-readable angle name (for logging)
        adset_name: Ad set name string
        config: Dict from config.yaml

    Returns:
        Dict with adset_id and name
    """
    token = _get_token()
    meta_config = config.get("meta", {})
    ad_account = meta_config.get("ad_account_id", "")
    daily_budget = meta_config.get("default_daily_budget", 2000)
    countries = meta_config.get("default_countries", ["US"])

    if not ad_account:
        raise ValueError("meta.ad_account_id not set in config.yaml")

    # Build targeting JSON
    import json
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


def draft_run_to_meta(run_data, config):
    """Draft an entire run to Meta as PAUSED campaigns + ad sets.

    Structure: 1 campaign per topic, 1 ad set per angle.

    Args:
        run_data: Dict from asset_library.json
        config: Dict from config.yaml

    Returns:
        Dict with:
            campaigns: list of {campaign_id, name, adsets: [{adset_id, name}]}
            total_campaigns: int
            total_adsets: int
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
            # Ad set name: {angle_slug}_{variant_count}vars
            n_vars = len(creative.get("variants", []))
            adset_name = f"{angle_slug}_{n_vars}vars"

            adset = create_draft_adset(
                campaign_id=campaign["campaign_id"],
                angle_name=creative.get("angle", "Unknown"),
                adset_name=adset_name,
                config=config,
            )
            adsets.append(adset)
            total_adsets += 1

        campaign["adsets"] = adsets
        results.append(campaign)

    logger.info(
        f"Drafted {len(results)} campaigns and {total_adsets} ad sets to Meta (PAUSED)"
    )

    return {
        "campaigns": results,
        "total_campaigns": len(results),
        "total_adsets": total_adsets,
    }

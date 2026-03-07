"""
Zip export — packages a completed run into a downloadable zip file.

Structure:
  run-{YYYYMMDD-HHMM}/
  ├── manifest.csv          (17 columns, one row per variant)
  ├── {topic-slug}/
  │   ├── {angle-slug}/
  │   │   ├── v1-direct.png
  │   │   ├── v2-hook.png
  │   │   └── copy.csv     (same columns, scoped to this angle)
"""

import csv
import io
import os
import re
import logging
import zipfile
from datetime import datetime

logger = logging.getLogger(__name__)

# Manifest / copy.csv column order
MANIFEST_COLUMNS = [
    "run_id",
    "topic",
    "topic_rank",
    "angle",
    "angle_type",
    "variant",
    "variant_style",
    "image_filename",
    "headline",
    "primary_text",
    "description",
    "cta",
    "source_url",
    "destination_network",
    "pv_domain",
    "buyer_initials",
    "num_source_ads",
    "generated_at",
]


def slugify(text):
    """Convert text to a URL-friendly slug (lowercase, hyphens, no special chars)."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")


def create_run_zip(run_data):
    """Package a completed run into a downloadable zip.

    Args:
        run_data: Dict from asset_library.json with keys:
            id, timestamp, source_url, network, pv_domain, buyer_initials,
            creatives (list of creative dicts)

    Returns:
        bytes — the zip file content ready for st.download_button
    """
    # Parse run timestamp for folder name and run_id
    ts_raw = run_data.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts_raw)
    except (ValueError, TypeError):
        dt = datetime.now()

    run_id = dt.strftime("%Y%m%d-%H%M")
    run_folder = f"run-{run_id}"
    generated_at = dt.isoformat() + "Z"

    # Shared fields from run-level data
    source_url = run_data.get("source_url", "")
    network = run_data.get("network", "")
    pv_domain = run_data.get("pv_domain", "")
    buyer_initials = run_data.get("buyer_initials", "")

    buffer = io.BytesIO()
    manifest_rows = []

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for creative in run_data.get("creatives", []):
            topic_name = creative.get("topic", "Unknown")
            topic_slug = slugify(creative.get("topic_slug", "") or topic_name)
            topic_rank = creative.get("topic_rank", "")
            angle_name = creative.get("angle", "Unknown")
            angle_slug = slugify(creative.get("angle_slug", "") or angle_name)
            intent_type = creative.get("intent_type", "info").upper()
            angle_count = creative.get("angle_count", 0)

            angle_rows = []

            for variant in creative.get("variants", []):
                vid = variant.get("variant_id", 1)
                vtype = variant.get("variant_type", "direct").upper()
                img_filename = f"v{vid}-{vtype.lower()}.png"
                rel_img_path = f"{topic_slug}/{angle_slug}/{img_filename}"

                # Read banner image from disk if it exists
                banner_path = variant.get("banner_path", "")
                if banner_path and os.path.isfile(str(banner_path)):
                    try:
                        with open(banner_path, "rb") as img_f:
                            zf.writestr(f"{run_folder}/{rel_img_path}", img_f.read())
                    except Exception as e:
                        logger.warning(f"Could not read banner {banner_path}: {e}")

                row = {
                    "run_id": run_id,
                    "topic": topic_name,
                    "topic_rank": topic_rank,
                    "angle": angle_name,
                    "angle_type": intent_type,
                    "variant": f"V{vid}",
                    "variant_style": vtype,
                    "image_filename": rel_img_path,
                    "headline": variant.get("headline", ""),
                    "primary_text": variant.get("primary_text", ""),
                    "description": "",
                    "cta": "Learn More",
                    "source_url": source_url,
                    "destination_network": network,
                    "pv_domain": pv_domain,
                    "buyer_initials": buyer_initials,
                    "num_source_ads": str(angle_count),
                    "generated_at": generated_at,
                }
                manifest_rows.append(row)
                angle_rows.append(row)

            # Write per-angle copy.csv
            if angle_rows:
                angle_csv = _rows_to_csv(angle_rows)
                zf.writestr(
                    f"{run_folder}/{topic_slug}/{angle_slug}/copy.csv",
                    angle_csv,
                )

        # Write root manifest.csv
        if manifest_rows:
            manifest_csv = _rows_to_csv(manifest_rows)
            zf.writestr(f"{run_folder}/manifest.csv", manifest_csv)

    buffer.seek(0)
    return buffer.getvalue()


def build_manifest_rows(run_data):
    """Build manifest row dicts from run_data (reused by both zip and sheets push).

    Returns:
        list of dicts with MANIFEST_COLUMNS keys
    """
    ts_raw = run_data.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts_raw)
    except (ValueError, TypeError):
        dt = datetime.now()

    run_id = dt.strftime("%Y%m%d-%H%M")
    generated_at = dt.isoformat() + "Z"
    source_url = run_data.get("source_url", "")
    network = run_data.get("network", "")
    pv_domain = run_data.get("pv_domain", "")
    buyer_initials = run_data.get("buyer_initials", "")

    rows = []
    for creative in run_data.get("creatives", []):
        topic_name = creative.get("topic", "Unknown")
        topic_slug = slugify(creative.get("topic_slug", "") or topic_name)
        topic_rank = creative.get("topic_rank", "")
        angle_name = creative.get("angle", "Unknown")
        angle_slug = slugify(creative.get("angle_slug", "") or angle_name)
        intent_type = creative.get("intent_type", "info").upper()
        angle_count = creative.get("angle_count", 0)

        for variant in creative.get("variants", []):
            vid = variant.get("variant_id", 1)
            vtype = variant.get("variant_type", "direct").upper()
            img_filename = f"v{vid}-{vtype.lower()}.png"
            rel_img_path = f"{topic_slug}/{angle_slug}/{img_filename}"

            rows.append({
                "run_id": run_id,
                "topic": topic_name,
                "topic_rank": topic_rank,
                "angle": angle_name,
                "angle_type": intent_type,
                "variant": f"V{vid}",
                "variant_style": vtype,
                "image_filename": rel_img_path,
                "headline": variant.get("headline", ""),
                "primary_text": variant.get("primary_text", ""),
                "description": "",
                "cta": "Learn More",
                "source_url": source_url,
                "destination_network": network,
                "pv_domain": pv_domain,
                "buyer_initials": buyer_initials,
                "num_source_ads": str(angle_count),
                "generated_at": generated_at,
            })

    return rows


def _rows_to_csv(rows):
    """Convert list of dicts to CSV string using MANIFEST_COLUMNS order."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=MANIFEST_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()

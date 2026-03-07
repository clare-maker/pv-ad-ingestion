"""
Google Sheets tracker — appends approved variants to a tracking sheet.
Uses gspread with service account credentials.

Supports two auth modes:
  1. Local: credentials.json file (set in config.yaml)
  2. Streamlit Cloud: secrets.toml with [gcp_service_account] section
"""

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def _get_gspread_client(config):
    """Get authenticated gspread client. Tries Streamlit secrets first, then file."""
    from google.oauth2.service_account import Credentials
    import gspread

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # Try Streamlit Cloud secrets first
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=scopes
            )
            return gspread.authorize(creds)
    except Exception:
        pass

    # Fall back to credentials file
    sheet_config = config.get("google_sheet", {})
    credentials_path = sheet_config.get("credentials_path", "credentials.json")
    if not os.path.isfile(credentials_path):
        raise FileNotFoundError(
            f"No credentials found. Either add {credentials_path} locally "
            f"or set [gcp_service_account] in Streamlit secrets."
        )
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return gspread.authorize(creds)

# Column headers for the tracker sheet (16 columns)
HEADERS = [
    "timestamp",
    "buyer_initials",
    "source_url",
    "network",
    "pv_domain",
    "campaign_name",
    "topic",
    "angle",
    "variant_id",
    "variant_type",
    "headline",
    "primary_text",
    "banner_text",
    "banner_path",
    "status",
]


def connect_to_sheet(config):
    """Authenticate and return the tracker worksheet."""
    import gspread

    sheet_config = config.get("google_sheet", {})
    spreadsheet_id = sheet_config.get("spreadsheet_id", "")
    sheet_name = sheet_config.get("sheet_name", "Ad Tracker")

    if not spreadsheet_id:
        raise ValueError(
            "No spreadsheet_id set in config.yaml. "
            "Create a Google Sheet and add its ID to config.yaml."
        )

    client = _get_gspread_client(config)
    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=sheet_name, rows=1000, cols=len(HEADERS)
        )
        logger.info(f"Created new worksheet: {sheet_name}")

    return worksheet


def ensure_headers(worksheet):
    """Add header row if the sheet is empty or headers don't match."""
    existing = worksheet.row_values(1)
    if not existing or existing[0] != HEADERS[0]:
        worksheet.insert_row(HEADERS, 1)
        logger.info("Added header row to tracker sheet")


def append_approved_variants(worksheet, approved_variants, source_url,
                              pv_domain, buyer_initials, network="facebook"):
    """Append one row per approved variant to the tracker sheet.

    Args:
        worksheet: gspread.Worksheet object
        approved_variants: List of dicts with variant data
        source_url: Original FB Ad Library URL or CSV filename
        pv_domain: Peak Ventures domain
        buyer_initials: Buyer's initials
        network: Destination network (facebook, taboola, gdn, tiktok)

    Returns:
        Number of rows appended
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_added = 0

    for v in approved_variants:
        if not v.get("approved", False):
            continue

        row = [
            timestamp,
            buyer_initials,
            source_url,
            network,
            pv_domain,
            v.get("campaign_name", ""),
            v.get("topic", ""),
            v.get("angle", ""),
            str(v.get("variant_id", "")),
            v.get("variant_type", ""),
            v.get("headline", ""),
            v.get("primary_text", ""),
            v.get("banner_text", ""),
            v.get("banner_path", ""),
            "generated",
        ]
        worksheet.append_row(row, value_input_option="USER_ENTERED")
        rows_added += 1

    logger.info(f"Appended {rows_added} rows to tracker sheet")
    return rows_added


# ──────────────────────────────────────────────
# Tracker tab push (GID-based, with duplicate detection)
# ──────────────────────────────────────────────

TRACKER_GID = 880439485

# Maps manifest field names → expected sheet column headers.
# Adjust right-side values if the actual sheet headers differ.
TRACKER_COLUMN_MAP = {
    "run_id": "run_id",
    "generated_at": "generated_at",
    "buyer_initials": "buyer_initials",
    "destination_network": "destination_network",
    "pv_domain": "pv_domain",
    "topic": "topic",
    "topic_rank": "topic_rank",
    "angle": "angle",
    "angle_type": "angle_type",
    "variant": "variant",
    "variant_style": "variant_style",
    "headline": "headline",
    "primary_text": "primary_text",
    "description": "description",
    "cta": "cta",
    "source_url": "source_url",
    "num_source_ads": "num_source_ads",
    "image_filename": "image_filename",
}


def connect_to_tracker_tab(config):
    """Authenticate and return the tracker worksheet identified by GID."""
    sheet_config = config.get("google_sheet", {})
    spreadsheet_id = sheet_config.get("spreadsheet_id", "")

    if not spreadsheet_id:
        raise ValueError("No spreadsheet_id set in config.yaml.")

    client = _get_gspread_client(config)
    spreadsheet = client.open_by_key(spreadsheet_id)

    # Find worksheet by GID
    for ws in spreadsheet.worksheets():
        if ws.id == TRACKER_GID:
            return ws

    raise ValueError(f"Worksheet with GID {TRACKER_GID} not found in spreadsheet.")


def run_already_pushed(worksheet, run_id):
    """Check if this run_id already has rows in the tracker sheet."""
    headers = worksheet.row_values(1)
    try:
        run_id_col = headers.index("run_id") + 1  # gspread is 1-indexed
    except ValueError:
        return False  # No run_id column, can't check

    existing_ids = worksheet.col_values(run_id_col)[1:]  # skip header
    return run_id in existing_ids


def push_run_to_tracker(worksheet, manifest_rows):
    """Append manifest rows to the tracker sheet, matching column order.

    Args:
        worksheet: gspread Worksheet (from connect_to_tracker_tab)
        manifest_rows: list of dicts with MANIFEST_COLUMNS keys
            (from exports.zip_export.build_manifest_rows)

    Returns:
        Number of rows appended
    """
    existing_headers = worksheet.row_values(1)
    if not existing_headers:
        logger.warning("Tracker sheet has no headers — cannot push.")
        return 0

    # Build a reverse map: sheet header → manifest field name
    header_to_field = {}
    for field, col_name in TRACKER_COLUMN_MAP.items():
        header_to_field[col_name] = field

    rows_to_append = []
    for manifest_row in manifest_rows:
        sheet_row = []
        for header in existing_headers:
            field = header_to_field.get(header)
            if field and field in manifest_row:
                sheet_row.append(str(manifest_row[field]))
            else:
                sheet_row.append("")
        rows_to_append.append(sheet_row)

    if rows_to_append:
        worksheet.append_rows(
            rows_to_append,
            value_input_option="USER_ENTERED",
        )

    logger.info(f"Pushed {len(rows_to_append)} rows to tracker tab (GID {TRACKER_GID})")
    return len(rows_to_append)

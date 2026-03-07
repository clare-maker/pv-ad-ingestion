"""
CSV fallback input — lets buyers upload a CSV of competitor ads
when the Playwright scraper isn't available or fails.
"""

import csv
import io
from scraper.normalizer import normalize_ad


def parse_csv_upload(uploaded_file):
    """Parse a CSV file upload into a list of normalized ad dicts.

    Args:
        uploaded_file: A Streamlit UploadedFile object (or any file-like with .read())

    Returns:
        List of normalized ad dicts matching the spec schema.
    """
    # Read the uploaded file content
    content = uploaded_file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    ads = []
    for i, row in enumerate(reader):
        # Pass the raw CSV row through the normalizer (handles flexible key names)
        normalized = normalize_ad(row)
        # Use row position as a frequency proxy (earlier = higher priority)
        normalized["frequency_count"] = len(ads) + 1
        ads.append(normalized)

    return ads

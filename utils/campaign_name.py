"""
Campaign naming convention builder.
Format: {topic_slug}:{angle_slug}-{pv_domain}-{buyer_initials}-{YYYYMMDD}
Example: auto-insurance-price-shock:rate-increase-alert-thepennypro.com-cbh-20260306
"""

from datetime import datetime


def build_campaign_name(topic_slug, angle_slug, pv_domain, buyer_initials, date=None):
    """Build a campaign name string from components.

    Args:
        topic_slug: Lowercase hyphenated topic (e.g. "auto-insurance-price-shock")
        angle_slug: Lowercase hyphenated angle (e.g. "rate-increase-alert")
        pv_domain: Peak Ventures domain (e.g. "thepennypro.com")
        buyer_initials: Buyer's initials (e.g. "cbh")
        date: Optional datetime object. Defaults to today.

    Returns:
        Full campaign name string.
    """
    if date is None:
        date = datetime.now()
    date_str = date.strftime("%Y%m%d")
    return f"{topic_slug}:{angle_slug}-{pv_domain}-{buyer_initials}-{date_str}"

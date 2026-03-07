"""
Clustering prompt template.
Classifies scraped ads into topic buckets with angle tags.
Surfaces actual offers, claims, and hooks from source ads for buyer review.
"""

CLUSTERING_PROMPT = """Given these {n} ads scraped from a competitor's Facebook Ad Library page, classify each ad into:

1. TOPIC BUCKET — the core subject (e.g. "auto insurance rates", "Medicare coverage", "home warranty"). Group ads about the same subject together even if wording differs.

2. ANGLE TAG — the persuasion hook used within that topic (e.g. "price shock", "new eligibility", "comparison/switcher", "urgency/deadline"). One ad = one angle.

3. OFFER/CLAIM — extract the specific offer, claim, or hook used in the ad. This is the concrete thing being advertised — e.g. "Costco iPhone Clearance", "$6000 Clinical Trial", "New 2026 Auto Rates", "Free Quote in 30 Seconds". Every angle should have at least one offer/claim extracted from the source ads.

Then return a ranked summary:

For each topic bucket:
- topic_label: short descriptive name
- topic_slug: lowercase, hyphenated (for campaign naming)
- ad_count: how many ads in this cluster
- avg_days_active: average run duration across ads in cluster
- top_destination: the most common destination domain in this cluster
- angles: array of distinct angles found, each with:
  - angle_label: short name
  - angle_slug: lowercase, hyphenated (for campaign naming)
  - angle_count: how many ads use this angle
  - intent_type: classify as "offer", "claim", "curiosity", or "info"
  - offers_and_claims: array of 1-3 specific offers/claims/hooks extracted verbatim or paraphrased from source ads. These are the actual things being advertised.
  - sample_headlines: 1-2 actual headlines from source ads
  - sample_primary_texts: 1-2 actual primary texts from source
  - sample_banner_texts: 1-2 banner/overlay texts observed or inferred from source ads

Rank topics by: ad_count DESC, then avg_days_active DESC.
Rank angles within each topic by: angle_count DESC.

Return valid JSON only. No markdown, no commentary.

Here are the ads:

{ads_json}"""

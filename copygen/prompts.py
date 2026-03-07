"""
Copy generation prompt template.
Produces exactly 2 variants per approved angle:
  Variant A: Offer/claim-heavy (direct, aggressive, scroll-stopping)
  Variant B: Curiosity/urgency (question hook, information gap, time pressure)
"""

COPYGEN_PROMPT = """You are an expert Facebook media buyer writing lead gen and arbitrage ad copy.
Your ads need to STOP THE SCROLL, generate curiosity, and drive clicks.

For each topic + angle below, generate exactly 2 Facebook ad copy variants.

Each variant must include:
- headline (max {hl_max} chars): Bold text below the image. Short, punchy, 5-8 words max.
- primary_text (max {pt_max} chars): Text above the image. Emotional trigger, provocative question, or teased reveal. Use line breaks and emojis strategically.
- banner_text (max {bt_max} chars): Bold text overlaid on the ad image. LOUDEST element — tabloid headline meets offer page.

## The 2 variants MUST use different strategies:

VARIANT 1 — "direct" style:
- Lead with the offer, claim, or value prop
- Price anchoring, savings hooks, bold assertions
- Banner text = the offer headline (e.g. "Costco iPhone Clearance", "New 2026 Rates Exposed")
- Feels like a deal page or breaking news

VARIANT 2 — "hook" style:
- Lead with a question, curiosity gap, or urgency trigger
- "Did you know...?", "Before you...", "Most people miss this..."
- Banner text = curiosity/urgency hook (e.g. "What They Won't Tell You", "Before March Ends...")
- Feels like the first line of a viral post

## Rules:
- Anchor to the offers/claims from the source data below — use real specifics
- Use [State] placeholder where geographic personalization applies
- Do NOT write generic/informational copy
- Do NOT exceed character limits
- Make each variant feel like it came from a completely different advertiser

## Topics and angles to generate for:

{selections_json}

Return valid JSON only:
{{
  "creatives": [
    {{
      "topic": "Topic Label",
      "topic_slug": "topic-slug",
      "angle": "Angle Label",
      "angle_slug": "angle-slug",
      "variants": [
        {{
          "variant_id": 1,
          "variant_type": "direct",
          "headline": "...",
          "primary_text": "...",
          "banner_text": "..."
        }},
        {{
          "variant_id": 2,
          "variant_type": "hook",
          "headline": "...",
          "primary_text": "...",
          "banner_text": "..."
        }}
      ]
    }}
  ]
}}

No markdown fences, no commentary — JSON only."""

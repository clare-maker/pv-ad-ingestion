"""
Topic clustering via Claude API.
Takes normalized ads and returns ranked topics with angles.
"""

import json
import logging
from clustering.prompts import CLUSTERING_PROMPT

logger = logging.getLogger(__name__)


def _strip_markdown_fences(text):
    """Remove markdown code fences (```json ... ```) if present."""
    text = text.strip()
    if text.startswith("```"):
        # Remove first line (```json or ```)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def cluster_ads(ads, claude_client, config):
    """Classify ads into topic buckets with angle tags using Claude.

    Args:
        ads: List of normalized ad dicts from scraper
        claude_client: Anthropic client instance
        config: Dict from config.yaml

    Returns:
        Dict with structure: {"topics": [{"rank", "topic_label", "topic_slug",
        "ad_count", "avg_days_active", "angles": [...]}]}
    """
    model = config.get("claude", {}).get("model", "claude-sonnet-4-5-20250929")
    max_tokens = config.get("claude", {}).get("clustering_max_tokens", 4096)

    # Build the prompt with the ads data
    # Only send the fields Claude needs (not the empty ones)
    ads_for_prompt = []
    for ad in ads:
        ads_for_prompt.append({
            "headline": ad.get("headline", ""),
            "primary_text": ad.get("primary_text", ""),
            "destination_domain": ad.get("destination_domain", ""),
            "run_duration_signal": ad.get("run_duration_signal", 0),
            "media_type": ad.get("media_type", "image"),
        })

    prompt = CLUSTERING_PROMPT.format(
        n=len(ads),
        ads_json=json.dumps(ads_for_prompt, indent=2),
    )

    # Call Claude API — retry up to 2 times on JSON parse failure
    for attempt in range(2):
        try:
            message = claude_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = message.content[0].text
            cleaned = _strip_markdown_fences(response_text)
            result = json.loads(cleaned)

            # Add rank numbers if not present
            for i, topic in enumerate(result.get("topics", [])):
                if "rank" not in topic:
                    topic["rank"] = i + 1

            logger.info(f"Clustering found {len(result.get('topics', []))} topics")
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed (attempt {attempt + 1}): {e}")
            if attempt == 0:
                # Retry with a stricter instruction
                prompt += "\n\nIMPORTANT: Return ONLY valid JSON. No markdown fences, no explanation."
                continue
            raise ValueError(
                f"Claude returned invalid JSON after 2 attempts. "
                f"Raw response: {response_text[:500]}"
            )
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise

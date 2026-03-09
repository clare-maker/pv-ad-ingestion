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
    configured_max = config.get("claude", {}).get("clustering_max_tokens", 16384)

    # Scale max_tokens based on number of ads — more ads = more topics = larger JSON
    # ~200 tokens per ad for output is a safe estimate
    estimated_need = max(4096, len(ads) * 200)
    max_tokens = min(max(configured_max, estimated_need), 32000)
    logger.info(f"Clustering {len(ads)} ads with max_tokens={max_tokens}")

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

    # Call Claude API with streaming (required for large/long responses)
    # Retry up to 2 times on JSON parse failure
    for attempt in range(2):
        try:
            # Use streaming to avoid timeout on large requests
            with claude_client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                response = stream.get_final_message()

            # Check if output was truncated
            if response.stop_reason == "max_tokens":
                logger.warning(
                    f"Clustering response truncated at {max_tokens} tokens "
                    f"(attempt {attempt + 1})"
                )
                if attempt == 0:
                    max_tokens = min(max_tokens * 2, 64000)
                    prompt += "\n\nIMPORTANT: Be more concise. Limit to top 15 topics max. Return ONLY valid JSON, no markdown fences."
                    continue
                raise ValueError(
                    f"Clustering response too large even at {max_tokens} tokens. "
                    f"Try scraping fewer ads per URL."
                )

            response_text = response.content[0].text
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
                prompt += "\n\nIMPORTANT: Return ONLY valid JSON. No markdown fences, no explanation."
                continue
            raise ValueError(
                f"Claude returned invalid JSON after 2 attempts. "
                f"Raw response: {response_text[:500]}"
            )
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise

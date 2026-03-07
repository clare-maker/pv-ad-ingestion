"""
Copy generation via Claude API.
Takes Gate 1 selections (topics + angles with source samples)
and generates copy variants.
"""

import json
import logging
from copygen.prompts import COPYGEN_PROMPT

logger = logging.getLogger(__name__)


def _strip_markdown_fences(text):
    """Remove markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def generate_copy(selections, claude_client, config):
    """Generate copy variants for each selected topic + angle.

    Args:
        selections: List of dicts from Gate 1, each with:
            topic_label, topic_slug, angles (list of angle dicts with
            angle_label, angle_slug, sample_headlines, sample_primary_texts, sample_banner_texts)
        claude_client: Anthropic client instance
        config: Dict from config.yaml

    Returns:
        Dict with structure: {"creatives": [{"topic", "topic_slug", "angle",
        "angle_slug", "variants": [{"variant_id", "headline", "primary_text", "banner_text"}]}]}
    """
    model = config.get("claude", {}).get("model", "claude-sonnet-4-5-20250929")
    max_tokens = config.get("claude", {}).get("copygen_max_tokens", 4096)
    copy_config = config.get("copy_generation", {})
    variants_per_angle = copy_config.get("variants_per_angle", 5)
    hl_max = copy_config.get("headline_max_chars", 40)
    pt_max = copy_config.get("primary_text_max_chars", 125)
    bt_max = copy_config.get("banner_text_max_chars", 60)

    # Build selections JSON for the prompt
    selections_for_prompt = []
    for sel in selections:
        for angle in sel.get("angles", []):
            selections_for_prompt.append({
                "topic_label": sel["topic_label"],
                "topic_slug": sel["topic_slug"],
                "angle_label": angle.get("angle_label", ""),
                "angle_slug": angle.get("angle_slug", ""),
                "sample_headlines": angle.get("sample_headlines", []),
                "sample_primary_texts": angle.get("sample_primary_texts", []),
                "sample_banner_texts": angle.get("sample_banner_texts", []),
            })

    prompt = COPYGEN_PROMPT.format(
        variants_per_angle=variants_per_angle,
        hl_max=hl_max,
        pt_max=pt_max,
        bt_max=bt_max,
        selections_json=json.dumps(selections_for_prompt, indent=2),
    )

    # Call Claude API — retry once on JSON parse failure
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

            # Enforce character limits (truncate if Claude exceeded them)
            for creative in result.get("creatives", []):
                for variant in creative.get("variants", []):
                    if len(variant.get("headline", "")) > hl_max:
                        logger.warning(f"Headline truncated: {variant['headline'][:50]}...")
                        variant["headline"] = variant["headline"][:hl_max]
                    if len(variant.get("primary_text", "")) > pt_max:
                        logger.warning(f"Primary text truncated")
                        variant["primary_text"] = variant["primary_text"][:pt_max]
                    if len(variant.get("banner_text", "")) > bt_max:
                        logger.warning(f"Banner text truncated")
                        variant["banner_text"] = variant["banner_text"][:bt_max]

            logger.info(f"Generated {len(result.get('creatives', []))} creative sets")
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

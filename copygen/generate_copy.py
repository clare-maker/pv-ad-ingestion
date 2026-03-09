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
    configured_max = config.get("claude", {}).get("copygen_max_tokens", 4096)
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

    # Scale max_tokens based on number of angles — ~500 tokens per angle for 2 variants
    n_angles = len(selections_for_prompt)
    estimated_need = max(4096, n_angles * 500)
    max_tokens = min(max(configured_max, estimated_need), 32000)
    logger.info(f"Generating copy for {n_angles} angles with max_tokens={max_tokens}")

    prompt = COPYGEN_PROMPT.format(
        variants_per_angle=variants_per_angle,
        hl_max=hl_max,
        pt_max=pt_max,
        bt_max=bt_max,
        selections_json=json.dumps(selections_for_prompt, indent=2),
    )

    # Call Claude API with streaming (avoids timeout on large requests)
    for attempt in range(2):
        try:
            with claude_client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                response = stream.get_final_message()

            # Check if output was truncated
            if response.stop_reason == "max_tokens":
                logger.warning(f"Copy response truncated at {max_tokens} tokens (attempt {attempt + 1})")
                if attempt == 0:
                    max_tokens = min(max_tokens * 2, 64000)
                    prompt += "\n\nIMPORTANT: Return ONLY valid JSON. No markdown fences. Be concise."
                    continue
                raise ValueError(f"Copy response too large even at {max_tokens} tokens.")

            response_text = response.content[0].text
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

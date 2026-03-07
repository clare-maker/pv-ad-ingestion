"""
Banner image generation via OpenAI GPT-Image-1.
Generates 1080x1080 Facebook ad banner images from banner_text + topic context.
Adapted from pv-ad_generation_v2 patterns.
"""

import os
import base64
import time
import logging
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/images/generations"
MAX_RETRIES = 3
RETRY_DELAY = 5

# ─── Prompt templates ───

PREAMBLE = """You are generating a professional Facebook ad banner image.
The canvas is exactly 1080x1080 pixels, square format.
This must look like a polished, agency-produced social media advertisement
— not a stock photo, not a mockup, not a generic image.
It is a finished ad creative ready to upload to Facebook Ads Manager.
All text must be rendered with perfect clarity — sharp, crisp letterforms
with zero blur, warping, or artifacts.

"""

# Template 1: Photo top (65%) + clean white bottom (35%) with headline + pill CTA
LAYOUT_PHOTO_CLEAN = """UPPER ZONE (top 65%):
A professional stock photograph fills this entire zone edge-to-edge
with no margins or borders. The photo depicts: {photo_concept}.

LOWER ZONE (bottom 35%):
A clean, solid white background fills this zone completely.

HEADLINE TEXT:
The headline reads exactly: "{banner_text}"
This text is rendered in a bold, heavyweight sans-serif font
(similar to Montserrat ExtraBold or Helvetica Bold).
The text is dark near-black colored.
It is LEFT-ALIGNED, starting from the left edge with moderate padding.
The text is LARGE — it should be the dominant element in the white zone.

CTA BUTTON:
In the bottom-right corner of the white zone, there is a small
pill-shaped button with a bold accent color background and white text
reading: "Learn More".

"""

# Template 2: Photo top (55%) + bold color bar bottom (45%) with centered headline
LAYOUT_COLOR_BAR = """UPPER ZONE (top 55-60%):
A professional stock photograph fills this entire zone edge-to-edge.
The photo depicts: {photo_concept}.

LOWER ZONE (bottom 40-45%):
A bold, solid navy blue colored rectangle fills this entire zone
edge-to-edge. This is a thick, prominent color bar.

HEADLINE TEXT:
The headline reads exactly: "{banner_text}"
The text is WHITE, bold heavyweight sans-serif font.
It is CENTERED horizontally within the color bar.
The text is VERY LARGE — it should dominate the color bar area.

CTA BUTTON:
Centered below the headline, a white pill-shaped button with navy blue
text reading: "Learn More".

"""

# Template 3: Full-bleed darkened photo + colored highlight boxes behind text
LAYOUT_HIGHLIGHT = """The entire 1080x1080 canvas is filled edge-to-edge with a single stock
photograph. The photo depicts: {photo_concept}.
The photo has a darkened treatment (about 30% darkened) so overlaid text
is readable.

HEADLINE TEXT WITH HIGHLIGHT BOXES:
The headline reads exactly: "{banner_text}"
Each LINE of text has a solid colored rectangle BEHIND it — like a
highlighter marker effect. The highlight rectangles are gold/amber colored,
and the text on top is WHITE, bold sans-serif.
The text is positioned in the center of the image, left-aligned.

CTA BAR:
At the very bottom, spanning full width, a solid navy blue bar
(about 8% of height). Inside, centered white text: "Learn More".

"""

NEGATIVE_CONSTRAINTS = """
CRITICAL RULES:
- Render ALL text EXACTLY as specified above, character for character.
  Do not add, remove, change, paraphrase, or abbreviate any word.
- Text must be perfectly legible, sharp, and crisp with zero artifacts.
- Use a clean, modern sans-serif typeface for all text.
- Do NOT add any logos, brand marks, watermarks, or icons anywhere.
- Do NOT add any text beyond what is explicitly specified above.
- Do NOT add decorative elements like sparkles, gradients, or lens flares.
- This is a FLAT, GRAPHIC advertisement — not a 3D render or mockup.
"""

TEMPLATES = [LAYOUT_PHOTO_CLEAN, LAYOUT_COLOR_BAR, LAYOUT_HIGHLIGHT]


def _infer_photo_concept(topic, angle, primary_text):
    """Generate a photo concept description from the ad context."""
    # Build a simple, relevant photo concept from the topic
    context = f"{topic} {angle}".lower()

    # Common vertical → photo mappings
    if any(w in context for w in ["insurance", "auto", "car", "vehicle", "driver"]):
        return "a person reviewing car insurance documents at a desk, warm lighting, professional setting"
    elif any(w in context for w in ["medicare", "health", "medical", "doctor"]):
        return "a confident senior couple walking outdoors in a park, healthy and active, soft natural lighting"
    elif any(w in context for w in ["home", "house", "mortgage", "real estate"]):
        return "a beautiful suburban home exterior with a green lawn, golden hour lighting"
    elif any(w in context for w in ["job", "career", "worker", "construction", "employment"]):
        return "a professional worker on a construction site wearing a hard hat, golden hour, confident pose"
    elif any(w in context for w in ["phone", "iphone", "samsung", "tech", "clearance"]):
        return "a sleek modern smartphone displayed on a clean white surface with soft lighting"
    elif any(w in context for w in ["wedding", "event", "party"]):
        return "an elegant outdoor wedding setup with flowers and string lights, warm golden tones"
    elif any(w in context for w in ["travel", "vacation", "trip", "flight"]):
        return "a stunning tropical beach at sunset with clear turquoise water"
    elif any(w in context for w in ["finance", "money", "loan", "credit", "debt", "savings"]):
        return "a person looking at financial charts on a laptop screen, modern office, warm lighting"
    elif any(w in context for w in ["weight", "diet", "fitness", "gym", "protein"]):
        return "an energetic person exercising outdoors in morning sunlight, healthy lifestyle"
    else:
        return f"a professional lifestyle scene related to {topic}, clean and modern, warm lighting"


def build_banner_prompt(banner_text, topic, angle, primary_text="", template_idx=0):
    """Build the full image generation prompt for a banner.

    Args:
        banner_text: The bold text to overlay on the image
        topic: Topic label for context
        angle: Angle label for context
        primary_text: Primary ad text for additional context
        template_idx: Which template layout to use (0-2)

    Returns:
        Full prompt string for OpenAI image generation
    """
    photo_concept = _infer_photo_concept(topic, angle, primary_text)
    template = TEMPLATES[template_idx % len(TEMPLATES)]

    layout = template.format(
        banner_text=banner_text,
        photo_concept=photo_concept,
    )

    return PREAMBLE + layout + NEGATIVE_CONSTRAINTS


def generate_banner_image(banner_text, topic, angle, primary_text="",
                          template_idx=0, config=None):
    """Generate a banner image and return the file path.

    Args:
        banner_text: Text to overlay on the banner
        topic: Topic label
        angle: Angle label
        primary_text: Supporting text for context
        template_idx: Template layout (0-2, rotated across variants)
        config: Dict from config.yaml

    Returns:
        Path to saved image file, or None on failure
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping banner generation")
        return None

    banner_config = (config or {}).get("banner", {})
    model = banner_config.get("model", "gpt-image-1")
    size = banner_config.get("size", "1024x1024")
    quality = banner_config.get("quality", "high")
    output_dir = Path(banner_config.get("output_dir", "output/banners"))
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_banner_prompt(banner_text, topic, angle, primary_text, template_idx)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
    }

    # Call OpenAI with retries
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                OPENAI_API_URL, headers=headers, json=payload, timeout=120
            )

            if resp.status_code == 429:
                wait = RETRY_DELAY * attempt
                logger.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()

            if "data" in data and len(data["data"]) > 0:
                img_data = data["data"][0]

                # Decode the image
                if "b64_json" in img_data:
                    image_bytes = base64.b64decode(img_data["b64_json"])
                elif "url" in img_data:
                    img_resp = requests.get(img_data["url"], timeout=60)
                    img_resp.raise_for_status()
                    image_bytes = img_resp.content
                else:
                    logger.error("No image data in response")
                    return None

                # Save to file
                safe_text = "".join(c if c.isalnum() else "_" for c in banner_text[:30])
                filename = f"banner_{safe_text}_{template_idx}.png"
                filepath = output_dir / filename
                filepath.write_bytes(image_bytes)

                logger.info(f"Banner saved: {filepath}")
                return str(filepath)

        except requests.exceptions.RequestException as e:
            logger.warning(f"Image gen attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue

    logger.error(f"Banner generation failed after {MAX_RETRIES} attempts")
    return None

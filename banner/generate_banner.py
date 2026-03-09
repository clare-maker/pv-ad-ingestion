"""
Banner image generation via OpenAI GPT-Image-1.
Generates 1080x1080 Facebook ad banner images from banner_text + topic context.
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

CRITICAL TEXT RULES:
- Render ALL text EXACTLY as specified, character for character.
- Text must be perfectly legible, sharp, and crisp with zero blur or artifacts.
- Use a clean, modern sans-serif typeface (like Montserrat Bold or Helvetica Bold).
- Do NOT add any extra text, logos, watermarks, icons, or decorative elements.
- Do NOT add any text beyond what is explicitly specified below.

"""

# Template 1: Photo top (65%) + clean white bottom (35%) with headline + pill CTA
LAYOUT_PHOTO_CLEAN = """UPPER ZONE (top 65%):
A high-quality photograph fills this entire zone edge-to-edge with no margins.
The photo depicts: {photo_concept}.
The photo should feel authentic and editorial — like a magazine feature, not a stock library.

LOWER ZONE (bottom 35%):
A clean, solid white background.

HEADLINE TEXT:
Centered in the white zone, the text reads exactly: "{banner_text}"
Bold, heavyweight sans-serif font. Dark near-black color.
The text should be LARGE — the dominant element in the white zone.

CTA BUTTON:
Below the headline, a small pill-shaped button with bold blue background
and white text reading: "Learn More".

"""

# Template 2: Full-bleed darkened photo + colored highlight boxes behind text
LAYOUT_HIGHLIGHT = """The entire 1080x1080 canvas is filled edge-to-edge with a single photograph.
The photo depicts: {photo_concept}.
The photo has a darkened treatment (about 35% darkened) so overlaid text is readable.

HEADLINE TEXT WITH HIGHLIGHT BOXES:
The headline reads exactly: "{banner_text}"
Each LINE of text has a solid colored rectangle BEHIND it — like a
highlighter marker effect. The highlight rectangles are gold/amber colored,
and the text on top is WHITE, bold sans-serif.
The text is positioned in the upper-center area of the image.

CTA BAR:
At the very bottom, spanning full width, a solid dark navy blue bar
(about 8% of height). Inside, centered white bold text: "Learn More".

"""

TEMPLATES = [LAYOUT_PHOTO_CLEAN, LAYOUT_HIGHLIGHT]


def _infer_photo_concept(topic, angle, banner_text):
    """Generate a specific, relevant photo concept from the ad context.

    Uses the banner_text and angle for specificity rather than just topic keywords.
    """
    # Combine all context for better matching
    context = f"{topic} {angle} {banner_text}".lower()

    # ── Specific verticals with targeted imagery ──

    # Automotive — differentiate between tires, insurance, buying, etc.
    if any(w in context for w in ["tire", "tyre", "wheel"]):
        return "close-up of a car's new tire on a clean road, shot from a low angle showing the tread pattern, natural daylight, automotive photography style"
    if any(w in context for w in ["car insurance", "auto insurance", "vehicle insurance"]):
        return "a couple happily receiving car keys at a dealership, bright modern showroom, warm lighting"
    if any(w in context for w in ["car deal", "car price", "new car", "used car", "dealership"]):
        return "a shiny new car in a showroom with dramatic lighting, reflections on the hood"
    if "jeep" in context or "truck" in context or "suv" in context:
        return "a rugged SUV/truck on an open highway with dramatic sky, adventure photography style"

    # Health & Medical
    if any(w in context for w in ["hair transplant", "hair restoration", "hair loss", "balding"]):
        return "a confident man in his 30s-40s running his hand through thick hair, natural lighting, portrait style"
    if any(w in context for w in ["dental", "dentist", "teeth", "smile"]):
        return "a person with a bright confident smile in natural light, close-up portrait, warm tones"
    if any(w in context for w in ["medicare", "senior health", "retirement health"]):
        return "an active senior couple walking on a scenic trail, golden hour sunlight, lifestyle photography"
    if any(w in context for w in ["weight loss", "diet", "fitness", "gym", "keto"]):
        return "an energetic person mid-workout with morning sunlight streaming in, dynamic action shot"
    if any(w in context for w in ["doctor", "medical", "health", "clinic", "treatment", "procedure"]):
        return "a warm, modern medical office with a doctor having a friendly conversation with a patient, bright and reassuring atmosphere"

    # Finance
    if any(w in context for w in ["mortgage", "home loan", "refinance"]):
        return "a family standing in front of a beautiful home with a sold sign, golden hour, joyful expressions"
    if any(w in context for w in ["debt", "credit card", "loan", "consolidat"]):
        return "a person looking relieved while reviewing paperwork at a kitchen table, warm home lighting"
    if any(w in context for w in ["savings", "invest", "retire", "401k", "finance"]):
        return "a person confidently using a laptop at a modern desk, warm office lighting, successful atmosphere"
    if any(w in context for w in ["insurance"]) and "car" not in context:
        return "a happy family in their living room, warm lighting, feeling of security and comfort"

    # Home & Property
    if any(w in context for w in ["solar", "energy", "panel"]):
        return "a modern home rooftop with sleek solar panels against a blue sky, architectural photography"
    if any(w in context for w in ["roofing", "roof", "gutter"]):
        return "a beautiful home exterior with a brand new roof, curb appeal shot, golden hour lighting"
    if any(w in context for w in ["home", "house", "property", "real estate"]):
        return "a stunning home exterior with manicured lawn, golden hour lighting, real estate photography"

    # Tech & Products
    if any(w in context for w in ["phone", "iphone", "samsung", "smartphone"]):
        return "a sleek smartphone on a minimalist surface with soft studio lighting, product photography"

    # Employment & Education
    if any(w in context for w in ["job", "career", "hiring", "employment", "salary"]):
        return "a confident professional walking into a modern office building, morning light, success energy"
    if any(w in context for w in ["construction", "trade", "electrician", "plumber", "hvac"]):
        return "a skilled tradesperson at work on a clean job site, golden hour, professional and capable"

    # Travel
    if any(w in context for w in ["travel", "vacation", "flight", "hotel", "cruise"]):
        return "a stunning travel destination with turquoise water and dramatic landscape, wanderlust photography"

    # Fallback — use the topic directly for a relevant scene
    return f"a compelling lifestyle scene closely related to {topic}, editorial photography style, warm natural lighting, authentic and relatable"


def build_banner_prompt(banner_text, topic, angle, primary_text="", template_idx=0):
    """Build the full image generation prompt for a banner.

    Args:
        banner_text: The bold text to overlay on the image
        topic: Topic label for context
        angle: Angle label for context
        primary_text: Primary ad text for additional context
        template_idx: Which template layout to use (0=clean white, 1=highlight)

    Returns:
        Full prompt string for OpenAI image generation
    """
    photo_concept = _infer_photo_concept(topic, angle, banner_text)
    template = TEMPLATES[template_idx % len(TEMPLATES)]

    layout = template.format(
        banner_text=banner_text,
        photo_concept=photo_concept,
    )

    return PREAMBLE + layout


def generate_banner_image(banner_text, topic, angle, primary_text="",
                          template_idx=0, config=None):
    """Generate a banner image and return the file path.

    Args:
        banner_text: Text to overlay on the banner
        topic: Topic label
        angle: Angle label
        primary_text: Supporting text for context
        template_idx: Template layout (0-1, rotated across variants)
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

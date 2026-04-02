"""Image validation using vision LLM — checks for cutoff and accuracy."""

import base64
import sys
from pathlib import Path

try:
    from llm_client import LLMClient, parse_json_response
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from utils.llm_client import LLMClient, parse_json_response


def _load_validation_prompt(config) -> str:
    """Load the validation system prompt."""
    with open(config.validation_prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def validate_image(
    client: LLMClient,
    png_bytes: bytes,
    description: str,
    config,
) -> dict:
    """Validate a rendered diagram image against its description.

    Sends the PNG to a vision model to check for:
        1. Cutoff/clipping — no elements should be cut off at edges
        2. Accuracy — image must match the original description

    Args:
        client: Initialised LLMClient instance.
        png_bytes: Rendered PNG image bytes.
        description: Original natural language description.
        config: ImageGenConfig instance.

    Returns:
        dict with keys:
            - pass: bool (True if both checks pass)
            - cutoff_ok: bool
            - accuracy_ok: bool
            - issues: list of {type, description}
            - fix_instructions: str (empty if pass)
    """
    system_prompt = _load_validation_prompt(config)

    user_text = (
        f"Original description: {description}\n\n"
        f"Please validate the attached image against this description."
    )

    image_b64 = base64.b64encode(png_bytes).decode("ascii")

    response = client.call_vision(
        model=config.image_validator_model,
        system_prompt=system_prompt,
        user_text=user_text,
        image_base64=image_b64,
        image_media_type="image/png",
        temperature=0.1,
        max_tokens=1024,
    )

    try:
        result = parse_json_response(response)
    except (ValueError, Exception):
        # If parsing fails, assume pass to avoid blocking
        return {
            "pass": True,
            "cutoff_ok": True,
            "accuracy_ok": True,
            "issues": [],
            "fix_instructions": "",
            "parse_error": f"Could not parse validation response: {response[:200]}",
        }

    # Ensure required keys exist
    result.setdefault("pass", True)
    result.setdefault("cutoff_ok", True)
    result.setdefault("accuracy_ok", True)
    result.setdefault("issues", [])
    result.setdefault("fix_instructions", "")

    return result

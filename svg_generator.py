"""LLM-based SVG generation from natural language descriptions.

Includes image validation: after generating SVG, renders to PNG and uses a
vision model to check for cutoff/clipping and accuracy against the description.
Auto-regenerates on failure (up to image_validation_retries attempts).
"""

import re
import xml.etree.ElementTree as ET

import sys
from pathlib import Path

try:
    from llm_client import LLMClient, parse_json_response
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from utils.llm_client import LLMClient, parse_json_response

from upload_imgur import svg_to_png
from validate_image import validate_image


def _load_system_prompt(config) -> str:
    """Load and populate the system prompt with styling constants."""
    with open(config.prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()

    styling_block = config.get_styling_block()
    prompt = prompt.replace("{{STYLING}}", styling_block)
    return prompt


def _extract_svg_and_metadata(response: str) -> tuple[str, dict]:
    """Extract SVG code and JSON metadata from LLM response.

    Returns (svg_string, metadata_dict).
    Raises ValueError if extraction fails.
    """
    # Extract SVG block — try various code fence formats, then bare <svg> tag
    svg_match = re.search(r"```(?:svg|xml|html)?\s*\n(.*?)```", response, re.DOTALL)
    if svg_match:
        # Verify the fenced block actually contains an <svg> tag
        inner = svg_match.group(1)
        if not re.search(r"<svg\b", inner):
            svg_match = None
    if not svg_match:
        svg_match = re.search(r"(<svg\b.*?</svg>)", response, re.DOTALL)
    if not svg_match:
        # Last resort: response may be truncated (no closing </svg> or ```)
        # Check if it starts with a code fence containing <svg
        trunc_match = re.search(r"```(?:svg|xml|html)?\s*\n(<svg\b.*)", response, re.DOTALL)
        if trunc_match:
            # Try to close the SVG tag so we get a partial diagram
            partial = trunc_match.group(1).strip().rstrip("`").strip()
            if "</svg>" not in partial:
                partial += "</svg>"
            svg_match = re.search(r"(<svg\b.*</svg>)", partial, re.DOTALL)
    if not svg_match:
        raise ValueError("No SVG code found in LLM response")

    svg_string = svg_match.group(1).strip()

    # Extract JSON metadata block
    json_match = re.search(r"```json\s*\n(.*?)```", response, re.DOTALL)
    if json_match:
        metadata = parse_json_response(json_match.group(1))
    else:
        try:
            metadata = parse_json_response(response[svg_match.end():])
        except (ValueError, Exception):
            metadata = {
                "type": "other",
                "title": "Generated diagram",
                "accessibility_description": "A mathematical diagram.",
            }

    return svg_string, metadata


def _validate_svg_xml(svg_string: str) -> tuple[bool, str]:
    """Validate that the SVG string is well-formed XML.

    Returns (is_valid, error_message).
    """
    try:
        ET.fromstring(svg_string)
        return True, ""
    except ET.ParseError as e:
        return False, str(e)


def _generate_with_xml_retry(
    client: LLMClient,
    description: str,
    config,
    system_prompt: str,
    w: int,
    h: int,
    extra_instructions: str = "",
) -> tuple[str, dict]:
    """Generate SVG and retry on XML validation errors.

    Returns (svg_string, metadata_dict).
    Raises RuntimeError if all attempts fail.
    """
    user_prompt = (
        f"Generate an SVG diagram with viewBox dimensions {w}x{h}.\n\n"
        f"Description: {description}"
    )
    if extra_instructions:
        user_prompt += f"\n\nIMPORTANT additional instructions:\n{extra_instructions}"

    response = client.call(
        model=config.model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    svg_string, metadata = _extract_svg_and_metadata(response)
    is_valid, error = _validate_svg_xml(svg_string)

    retries = 0
    while not is_valid and retries < config.validation_retries:
        retries += 1
        retry_prompt = (
            f"Your previous SVG had an XML parsing error:\n{error}\n\n"
            f"Please fix the SVG and return corrected output. "
            f"Original request: {description}\n"
            f"Dimensions: {w}x{h}"
        )
        if extra_instructions:
            retry_prompt += f"\n\nAlso apply these fixes:\n{extra_instructions}"

        response = client.call(
            model=config.model,
            system_prompt=system_prompt,
            user_prompt=retry_prompt,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        svg_string, metadata = _extract_svg_and_metadata(response)
        is_valid, error = _validate_svg_xml(svg_string)

    if not is_valid:
        raise RuntimeError(
            f"SVG generation failed after {retries + 1} attempts. "
            f"Last error: {error}"
        )

    return svg_string, metadata


def generate_svg(
    client: LLMClient,
    description: str,
    config,
    width: int = None,
    height: int = None,
    initial_fix_instructions: str = "",
) -> tuple[str, dict]:
    """Generate an SVG diagram with image validation.

    Flow:
        1. Generate SVG via LLM
        2. Validate XML structure
        3. Render to PNG via headless Chromium
        4. Validate image (cutoff + accuracy) via vision model
        5. If validation fails, regenerate with fix instructions
        6. Repeat up to image_validation_retries times

    Args:
        client: Initialised LLMClient instance.
        description: Natural language description of the diagram.
        config: ImageGenConfig instance.
        width: SVG width override (defaults to config value).
        height: SVG height override (defaults to config value).
        initial_fix_instructions: Optional fix instructions from a previous
            failed validation (used for manual retries).

    Returns:
        (svg_string, metadata_dict) where metadata contains type, title,
        accessibility_description, validation info, and _png_bytes (the
        last rendered PNG, reusable for upload to avoid re-rendering).

    Raises:
        RuntimeError: If SVG generation fails after all retries.
    """
    w = width or config.default_width
    h = height or config.default_height

    system_prompt = _load_system_prompt(config)

    # --- Attempt 1: generate SVG ---
    svg_string, metadata = _generate_with_xml_retry(
        client, description, config, system_prompt, w, h,
        extra_instructions=initial_fix_instructions,
    )

    # --- Image validation loop ---
    max_image_retries = config.image_validation_retries
    extra_instructions = ""
    last_png_bytes = None

    for attempt in range(max_image_retries + 1):
        # Render SVG to PNG
        try:
            png_bytes = svg_to_png(svg_string, w, h)
            last_png_bytes = png_bytes
        except Exception as e:
            # If PNG rendering fails, skip validation
            metadata["validation"] = {
                "status": "skipped",
                "reason": f"PNG render failed: {e}",
                "attempts": attempt + 1,
            }
            break

        # Validate image
        try:
            result = validate_image(client, png_bytes, description, config)
        except Exception as e:
            # If validation call fails, skip and use current SVG
            metadata["validation"] = {
                "status": "skipped",
                "reason": f"Validation call failed: {e}",
                "attempts": attempt + 1,
            }
            break

        if result["pass"]:
            # All checks passed
            metadata["validation"] = {
                "status": "passed",
                "attempts": attempt + 1,
            }
            break

        # --- Validation failed ---
        issues_summary = "; ".join(
            f"[{iss['type']}] {iss['description']}" for iss in result.get("issues", [])
        )
        fix_instructions = result.get("fix_instructions", "")

        if attempt < max_image_retries:
            # Regenerate with fix instructions
            extra_instructions = fix_instructions or (
                f"The previous diagram had these issues: {issues_summary}. "
                f"Please fix them."
            )

            try:
                svg_string, metadata = _generate_with_xml_retry(
                    client, description, config, system_prompt, w, h,
                    extra_instructions=extra_instructions,
                )
            except RuntimeError:
                # If regeneration fails, use the last valid SVG
                metadata["validation"] = {
                    "status": "failed",
                    "issues": result.get("issues", []),
                    "fix_instructions": fix_instructions,
                    "attempts": attempt + 1,
                    "reason": "Regeneration failed",
                }
                break
        else:
            # Exhausted all retries — return best effort
            metadata["validation"] = {
                "status": "failed",
                "issues": result.get("issues", []),
                "fix_instructions": fix_instructions,
                "attempts": attempt + 1,
            }

    # Attach the last rendered PNG so callers can reuse it for upload
    metadata["_png_bytes"] = last_png_bytes

    return svg_string, metadata

"""Generate DraftImage JSX snippets — supports both base64 data URI and HTTPS URLs.

Also provides JSX parsing utilities for finding placeholder images and
applying replacements.
"""

import base64
import re
import uuid


def svg_to_data_uri(svg_string: str) -> str:
    """Convert an SVG string to a base64 data URI."""
    encoded = base64.b64encode(svg_string.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def format_draft_image(
    svg_string: str,
    metadata: dict,
    width: int = 260,
    height: int = 260,
) -> str:
    """Generate a <DraftImage> JSX snippet with placeholder URL.

    Used when upload is not enabled — the URL is set to a placeholder
    so the user knows to upload the image first.

    Args:
        svg_string: Raw SVG content string.
        metadata: Metadata dict with at least 'accessibility_description'.
        width: Display width.
        height: Display height.

    Returns:
        Formatted <DraftImage> JSX string.
    """
    desc = metadata.get("accessibility_description", "A mathematical diagram.")
    image_id = str(uuid.uuid4())

    return (
        f"<DraftImage\n"
        f"  width={{{width}}}\n"
        f"  height={{{height}}}\n"
        f'  id="{image_id}"\n'
        f'  url="upload this image first"\n'
        f'  notesForImageCreator="{desc}"\n'
        f"/>"
    )


def format_draft_image_url(
    url: str,
    metadata: dict,
    width: int = 260,
    height: int = 260,
) -> str:
    """Generate a <DraftImage> JSX snippet with an HTTPS URL (e.g. Imgur).

    Args:
        url: HTTPS image URL (e.g. https://i.imgur.com/XXXXX.jpg).
        metadata: Metadata dict with at least 'accessibility_description'.
        width: Display width.
        height: Display height.

    Returns:
        Formatted <DraftImage> JSX string.
    """
    desc = metadata.get("accessibility_description", "A mathematical diagram.")
    image_id = str(uuid.uuid4())

    return (
        f"<DraftImage\n"
        f"  width={{{width}}}\n"
        f"  height={{{height}}}\n"
        f'  id="{image_id}"\n'
        f'  url="{url}"\n'
        f'  notesForImageCreator="{desc}"\n'
        f"/>"
    )


# ---------------------------------------------------------------------------
# JSX Parsing — find placeholder images and apply replacements
# ---------------------------------------------------------------------------

# Matches <DraftImage .../> or <Image .../> containing the placeholder
# path "image-coming-soon.svg".
# Uses re.DOTALL so attributes can span multiple lines.
_PLACEHOLDER_TAG_RE = re.compile(
    r"<(DraftImage|Image)\s+"  # opening tag: DraftImage or Image
    r"((?:[^>]|\n)*?"  # attributes before the path/url
    r"(?:path|url|src)\s*=\s*\"[^\"]*image-coming-soon[^\"]*\""  # placeholder marker
    r"(?:[^>]|\n)*?)"  # attributes after
    r"/\s*>",  # self-closing
    re.DOTALL,
)

# Attribute extractors
_ATTR_STR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')  # key="value"
_ATTR_JSX_RE = re.compile(r"(\w+)\s*=\s*\{(\d+)\}")  # key={123}


def _extract_attrs(attr_text: str) -> dict:
    """Extract string and JSX-expression attributes from a tag body."""
    attrs = {}
    for m in _ATTR_STR_RE.finditer(attr_text):
        attrs[m.group(1)] = m.group(2)
    for m in _ATTR_JSX_RE.finditer(attr_text):
        attrs[m.group(1)] = int(m.group(2))
    return attrs


def parse_jsx_placeholders(content: str) -> list[dict]:
    """Find all placeholder <Image> / <DraftImage> tags in JSX content.

    Returns a list of dicts, each with:
        - index: sequential number
        - tag: "Image" or "DraftImage"
        - description: extracted from accessibilityDescription or notesForImageCreator
        - width: int (default 260)
        - height: int (default 260)
        - char_start: start position in content string
        - char_end: end position in content string
        - original_text: the full matched tag text
    """
    placeholders = []
    for i, m in enumerate(_PLACEHOLDER_TAG_RE.finditer(content)):
        tag_name = m.group(1)
        attr_text = m.group(2)
        attrs = _extract_attrs(attr_text)

        # Try multiple attribute names for the description
        desc = (
            attrs.get("accessibilityDescription")
            or attrs.get("notesForImageCreator")
            or attrs.get("alt")
            or ""
        )

        placeholders.append(
            {
                "index": i,
                "tag": tag_name,
                "description": desc,
                "width": int(attrs.get("width", 260)),
                "height": int(attrs.get("height", 260)),
                "char_start": m.start(),
                "char_end": m.end(),
                "original_text": m.group(0),
            }
        )
    return placeholders


def apply_jsx_replacements(
    content: str, replacements: list[dict]
) -> str:
    """Replace placeholder tags in JSX content with new DraftImage code.

    Each replacement dict must have:
        - char_start: int
        - char_end: int
        - new_code: str (the replacement DraftImage JSX)

    Applies replacements in reverse position order to avoid offset drift.
    Preserves the original indentation of each replaced tag.
    """
    sorted_reps = sorted(replacements, key=lambda r: r["char_start"], reverse=True)
    for rep in sorted_reps:
        start = rep["char_start"]
        end = rep["char_end"]
        new_code = rep["new_code"]

        # Detect original indentation (whitespace before the tag on its line)
        line_start = content.rfind("\n", 0, start) + 1
        indent = ""
        for ch in content[line_start:start]:
            if ch in " \t":
                indent += ch
            else:
                break

        # Apply indentation to each line of the replacement (except the first)
        if indent:
            lines = new_code.split("\n")
            indented = lines[0] + "\n" + "\n".join(indent + ln for ln in lines[1:])
            new_code = indented

        content = content[:start] + new_code + content[end:]
    return content

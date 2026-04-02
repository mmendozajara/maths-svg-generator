"""Sync design tokens from a Figma file into the generator's YAML config.

Reads fill colors, stroke colors, fonts, font sizes, and stroke widths from
a Figma file via the REST API, then updates the styling section of the
project config YAML.

Usage:
    python sync_figma_styles.py
    python sync_figma_styles.py --file-key YOUR_KEY --node-id 1:50
    python sync_figma_styles.py --config project-configs/custom.yaml
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv


# Default Figma file
DEFAULT_FILE_KEY = "a0tmCxqT99VBlzgpXkddtv"
DEFAULT_NODE_ID = "1:50"  # Guidelines page


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert 0-1 RGB floats to hex string."""
    return "#{:02X}{:02X}{:02X}".format(int(r * 255), int(g * 255), int(b * 255))


def fetch_figma_node(token: str, file_key: str, node_id: str = None) -> dict:
    """Fetch a Figma file (or specific node) via REST API."""
    params = {}
    if node_id:
        params["ids"] = node_id
    resp = requests.get(
        f"https://api.figma.com/v1/files/{file_key}",
        headers={"X-Figma-Token": token},
        params=params,
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Figma API error {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def extract_tokens(node: dict) -> dict:
    """Walk a Figma node tree and extract design tokens.

    Returns a dict with:
        fill_colors: Counter of hex colors
        stroke_colors: Counter of hex colors
        fonts: Counter of font families
        font_sizes: Counter of sizes
        stroke_widths: set of widths
    """
    fill_colors = Counter()
    stroke_colors = Counter()
    fonts = Counter()
    font_sizes = Counter()
    stroke_widths = set()

    def walk(n):
        # Fills
        for fill in n.get("fills", []):
            if fill.get("type") == "SOLID" and fill.get("visible", True):
                c = fill.get("color", {})
                hex_c = rgb_to_hex(c.get("r", 0), c.get("g", 0), c.get("b", 0))
                fill_colors[hex_c] += 1

        # Strokes
        for stroke in n.get("strokes", []):
            if stroke.get("type") == "SOLID" and stroke.get("visible", True):
                c = stroke.get("color", {})
                hex_c = rgb_to_hex(c.get("r", 0), c.get("g", 0), c.get("b", 0))
                stroke_colors[hex_c] += 1

        sw = n.get("strokeWeight")
        if sw and sw > 0:
            stroke_widths.add(round(sw, 1))

        # Text
        style = n.get("style", {})
        if style:
            ff = style.get("fontFamily")
            if ff:
                fonts[ff] += 1
            fs = style.get("fontSize")
            if fs:
                font_sizes[fs] += 1

        for child in n.get("children", []):
            walk(child)

    walk(node)
    return {
        "fill_colors": fill_colors,
        "stroke_colors": stroke_colors,
        "fonts": fonts,
        "font_sizes": font_sizes,
        "stroke_widths": sorted(stroke_widths),
    }


def map_tokens_to_styling(tokens: dict) -> dict:
    """Map extracted Figma tokens to the generator's styling config.

    Uses frequency analysis to assign semantic roles:
    - Most common dark fill → axis_color
    - Most common accent fill → primary_color
    - etc.
    """
    fills = tokens["fill_colors"].most_common(20)
    strokes = tokens["stroke_colors"].most_common(10)
    fonts_ranked = tokens["fonts"].most_common(5)
    sizes_ranked = tokens["font_sizes"].most_common(5)

    # Classify colors by luminance
    def luminance(hex_c: str) -> float:
        r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)
        return 0.299 * r + 0.587 * g + 0.114 * b

    dark_fills = [(c, n) for c, n in fills if luminance(c) < 100]
    mid_fills = [(c, n) for c, n in fills if 100 <= luminance(c) < 200]
    light_fills = [(c, n) for c, n in fills if luminance(c) >= 200]

    # Assign roles
    axis_color = dark_fills[0][0] if dark_fills else "#333333"

    # Primary: most common mid-tone or accent color (skip the dominant dark)
    primary_candidates = [(c, n) for c, n in fills if c != axis_color and luminance(c) < 200]
    primary_color = primary_candidates[0][0] if primary_candidates else "#2563EB"

    # Secondary: next most common accent
    secondary_candidates = [
        (c, n) for c, n in primary_candidates if c != primary_color
    ]
    secondary_color = secondary_candidates[0][0] if secondary_candidates else "#DC2626"

    # Accent: third color
    accent_candidates = [
        (c, n) for c, n in secondary_candidates if c != secondary_color
    ]
    accent_color = accent_candidates[0][0] if accent_candidates else "#059669"

    # Light fills
    light_bg = light_fills[0][0] if light_fills else "#F1F2F3"
    fill_color = (
        light_fills[1][0]
        if len(light_fills) > 1
        else light_fills[0][0]
        if light_fills
        else "#DBEAFE"
    )

    # Grid color: light stroke
    light_strokes = [(c, n) for c, n in strokes if luminance(c) >= 180]
    grid_color = light_strokes[0][0] if light_strokes else "#E0E0E0"

    # Red/highlight for special markup
    red_strokes = [
        (c, n) for c, n in strokes if c.upper().startswith("#FF") or c.upper().startswith("#E0") or c.upper().startswith("#DC")
    ]

    # Fonts: prefer the math font for labels, UI font as secondary
    math_fonts = [f for f, _ in fonts_ranked if "katex" in f.lower() or "math" in f.lower()]
    ui_fonts = [f for f, _ in fonts_ranked if f not in math_fonts]

    # Build font-family string
    if ui_fonts:
        font_family = f"{ui_fonts[0]}, Arial, Helvetica, sans-serif"
    else:
        font_family = "Arial, Helvetica, sans-serif"

    math_font = math_fonts[0] if math_fonts else None

    # Font size: most common
    font_size = int(sizes_ranked[0][0]) if sizes_ranked else 14

    # Stroke width: pick the most common usable weight (1-3px range)
    usable_widths = [w for w in tokens["stroke_widths"] if 1.0 <= w <= 4.0]
    stroke_width = 2.0
    if usable_widths:
        # Pick the most common from the original data
        stroke_width = max(
            usable_widths,
            key=lambda w: sum(1 for sw in tokens["stroke_widths"] if sw == w),
        )

    styling = {
        "font_family": font_family,
        "font_size": font_size,
        "title_font_size": font_size + 4,
        "primary_color": primary_color,
        "secondary_color": secondary_color,
        "accent_color": accent_color,
        "axis_color": axis_color,
        "grid_color": grid_color,
        "fill_color": fill_color,
        "background": "#FFFFFF",
        "stroke_width": stroke_width,
        "axis_stroke_width": round(stroke_width * 0.75, 1),
        "point_radius": 4,
    }

    if math_font:
        styling["math_font"] = math_font

    return styling


def update_yaml_config(config_path: Path, new_styling: dict):
    """Update the styling section of a YAML config file."""
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    old_styling = raw.get("styling", {})
    raw["styling"] = new_styling

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Report changes
    changed = []
    for key in new_styling:
        old_val = old_styling.get(key)
        new_val = new_styling[key]
        if old_val != new_val:
            changed.append(f"  {key}: {old_val} -> {new_val}")

    return changed


def main():
    parser = argparse.ArgumentParser(description="Sync Figma design tokens to SVG generator config")
    parser.add_argument("--file-key", default=DEFAULT_FILE_KEY, help="Figma file key")
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID, help="Figma node ID to scan (e.g., page ID)")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "project-configs" / "default.yaml"),
        help="Path to YAML config to update",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print extracted styles without updating config")
    args = parser.parse_args()

    # Load env
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    token = os.environ.get("FIGMA_API_TOKEN", "")
    if not token:
        print("Error: FIGMA_API_TOKEN not set in .env or environment.")
        sys.exit(1)

    print(f"Fetching Figma file {args.file_key} (node: {args.node_id})...")
    data = fetch_figma_node(token, args.file_key, args.node_id)
    file_name = data.get("name", "unknown")
    print(f"File: {file_name}")

    # Find the target node
    doc = data.get("document", {})
    target = None
    for page in doc.get("children", []):
        if args.node_id and page.get("id") == args.node_id:
            target = page
            break
    if target is None:
        target = doc  # Scan the whole file

    print(f"Scanning node: {target.get('name', 'document')}...")
    tokens = extract_tokens(target)

    print(f"\nExtracted tokens:")
    print(f"  Fill colors: {len(tokens['fill_colors'])} unique")
    print(f"  Stroke colors: {len(tokens['stroke_colors'])} unique")
    print(f"  Fonts: {', '.join(f for f, _ in tokens['fonts'].most_common(5))}")
    print(f"  Font sizes: {', '.join(str(int(s)) + 'px' for s, _ in tokens['font_sizes'].most_common(5))}")
    print(f"  Stroke widths: {len(tokens['stroke_widths'])} unique")

    # Map to styling config
    styling = map_tokens_to_styling(tokens)

    print(f"\nMapped styling:")
    for key, val in styling.items():
        print(f"  {key}: {val}")

    if args.dry_run:
        print("\n(dry run — config not updated)")
        return

    config_path = Path(args.config)
    changes = update_yaml_config(config_path, styling)

    if changes:
        print(f"\nUpdated {config_path}:")
        for c in changes:
            print(c)
    else:
        print(f"\nNo changes needed — config already matches.")

    print("\nDone. Run `python generate.py` to use the synced styles.")


if __name__ == "__main__":
    main()

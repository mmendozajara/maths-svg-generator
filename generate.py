"""CLI entry point for the Maths SVG Image Generator.

Usage:
    # Single image
    python generate.py "A number line from 0 to 10 with 3 and 7 marked"

    # With options
    python generate.py "A right triangle with sides 3, 4, 5" --name triangle_345 --width 300 --height 300

    # Upload and get HTTPS URL in DraftImage
    python generate.py "A number line from 0 to 10" --upload

    # Batch from TXT file (one description per line)
    python generate.py --batch descriptions.txt --upload

    # Batch from JSON file
    python generate.py --batch requests.json --upload

    # JSX file processing — find placeholder images and generate replacements
    python generate.py --jsx input.jsx --upload
    python generate.py --jsx input.jsx --upload --output output_dir/

    # Dry run (print LLM response, don't save)
    python generate.py "A bar chart of pets: dogs 5, cats 3" --dry-run

    # Custom config
    python generate.py "A coordinate graph" --config project-configs/custom.yaml
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add parent utils to path (for local dev)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ImageGenConfig
from svg_generator import generate_svg
from jsx_embed import (
    format_draft_image,
    format_draft_image_url,
    parse_jsx_placeholders,
    apply_jsx_replacements,
)
from upload_imgur import upload_svg

try:
    from llm_client import LLMClient
except ImportError:
    from utils.llm_client import LLMClient


def _sanitize_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    safe = name.lower().strip()
    safe = safe.replace(" ", "_")
    # Keep only alphanumeric, underscore, hyphen
    safe = "".join(c for c in safe if c.isalnum() or c in "_-")
    return safe[:80] or "diagram"


def _generate_single(
    client: LLMClient,
    description: str,
    config: ImageGenConfig,
    name: str = None,
    width: int = None,
    height: int = None,
    dry_run: bool = False,
    upload: bool = False,
) -> dict | None:
    """Generate a single SVG from a description.

    Returns a result dict or None on failure.
    """
    w = width or config.default_width
    h = height or config.default_height

    print(f"\n{'='*60}")
    print(f"Generating: {description[:80]}...")
    print(f"Dimensions: {w}x{h}")

    start = time.time()
    try:
        svg_string, metadata = generate_svg(client, description, config, w, h)
    except (RuntimeError, ValueError) as e:
        print(f"  FAILED: {e}")
        return None
    elapsed = time.time() - start

    # Extract cached PNG bytes to avoid re-rendering for upload
    cached_png = metadata.pop("_png_bytes", None)

    print(f"  Type: {metadata.get('type', 'unknown')}")
    print(f"  Title: {metadata.get('title', 'N/A')}")

    # Show validation info
    v = metadata.get("validation", {})
    v_status = v.get("status", "none")
    v_attempts = v.get("attempts", 1)
    if v_status == "passed":
        retry_info = f" (retried {v_attempts - 1}x)" if v_attempts > 1 else ""
        print(f"  Validation: PASSED{retry_info}")
    elif v_status == "failed":
        issues = v.get("issues", [])
        retry_info = f" after {v_attempts} attempt(s)" if v_attempts > 1 else ""
        print(f"  Validation: ISSUES REMAIN{retry_info}")
        for iss in issues:
            print(f"    - [{iss.get('type', '?')}] {iss.get('description', '')}")
    elif v_status == "skipped":
        print(f"  Validation: skipped ({v.get('reason', 'unknown')})")

    print(f"  Generated in {elapsed:.1f}s")

    if dry_run:
        print(f"\n--- SVG Preview (first 500 chars) ---")
        print(svg_string[:500])
        print(f"\n--- Metadata ---")
        print(json.dumps(metadata, indent=2))
        return {"description": description, "metadata": metadata, "saved": False}

    # Determine filename
    if name:
        filename = f"{_sanitize_filename(name)}.svg"
    else:
        diagram_type = metadata.get("type", "diagram")
        timestamp = int(time.time())
        filename = f"{_sanitize_filename(diagram_type)}_{timestamp}.svg"

    # Save SVG locally
    config.ensure_output_dir()
    output_path = config.output_dir / filename
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_string)
    print(f"  Saved: {output_path}")

    result = {
        "description": description,
        "filename": filename,
        "path": str(output_path),
        "metadata": metadata,
        "saved": True,
    }

    # Upload and generate URL-based DraftImage
    if upload:
        print(f"  Uploading...")
        try:
            upload_result = upload_svg(
                svg_content=svg_string,
                width=w,
                height=h,
                title=metadata.get("title", "Maths Diagram"),
                description=metadata.get("accessibility_description", ""),
                png_bytes=cached_png,
            )
            hosted_url = upload_result["url"]
            host_name = upload_result["host"]
            print(f"  {host_name} URL: {hosted_url}")

            draft = format_draft_image_url(hosted_url, metadata, w, h)
            print(f"\n--- DraftImage Embed ({host_name}) ---")
            print(draft)

            result["hosted_url"] = hosted_url
            result["upload_host"] = host_name
        except Exception as e:
            print(f"  Upload FAILED: {e}")
            # Fall back to base64 embed
            print(f"  Falling back to base64 embed...")
            draft = format_draft_image(svg_string, metadata, w, h)
            print(f"\n--- DraftImage Embed (base64 fallback) ---")
            print(draft)
    else:
        # Default: base64 embed
        draft = format_draft_image(svg_string, metadata, w, h)
        print(f"\n--- DraftImage Embed ---")
        print(draft)

    result["draft_image"] = draft
    return result


def _parse_batch_file(batch_path: str) -> list[dict]:
    """Parse a batch file — supports .txt and .json formats.

    TXT format (one per line, optional name prefix):
        A number line from -5 to 5
        triangle | A right triangle with sides 3, 4, 5
        pie_chart | A pie chart showing 40% red, 35% blue

    JSON format:
        [
            {"id": "img001", "description": "A number line from -5 to 5"},
            {"id": "img002", "description": "A coordinate graph", "width": 300}
        ]

    Returns a list of dicts with keys: description, id (optional), width/height (optional).
    """
    path = Path(batch_path)
    ext = path.suffix.lower()

    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print("Error: JSON batch file must contain an array of objects.")
            return []
        return data

    # TXT / CSV / any text file — one description per line
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    items = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Support "name | description" format
        if "|" in line:
            parts = line.split("|", 1)
            items.append({
                "id": parts[0].strip(),
                "description": parts[1].strip(),
            })
        else:
            items.append({"description": line})
    return items


def _run_batch(
    client: LLMClient,
    batch_path: str,
    config: ImageGenConfig,
    width: int = None,
    height: int = None,
    dry_run: bool = False,
    upload: bool = False,
) -> list[dict]:
    """Run batch generation from a TXT or JSON file."""
    requests_data = _parse_batch_file(batch_path)
    if not requests_data:
        print("Error: no items found in batch file.")
        return []

    print(f"Batch mode: {len(requests_data)} diagram(s) to generate")
    print(f"Source: {batch_path}")
    results = []

    for i, req in enumerate(requests_data, 1):
        desc = req.get("description", "")
        if not desc:
            print(f"  Skipping item {i}: no description")
            continue

        name = req.get("id", None)
        w = req.get("width", width)
        h = req.get("height", height)

        print(f"\n[{i}/{len(requests_data)}]")
        result = _generate_single(client, desc, config, name, w, h, dry_run, upload)
        if result:
            results.append(result)

    return results


def _run_jsx(
    client: LLMClient,
    jsx_path: str,
    config: ImageGenConfig,
    upload: bool = False,
    output_dir: str = None,
) -> dict:
    """Process a JSX file — find placeholder images, generate SVGs, output modified JSX.

    Returns a summary dict with counts and the output file path.
    """
    jsx_file = Path(jsx_path)
    if not jsx_file.exists():
        print(f"Error: JSX file not found: {jsx_path}")
        return {"error": "File not found"}

    print(f"\nJSX Processor")
    print(f"  Input: {jsx_file.name}")

    content = jsx_file.read_text(encoding="utf-8")
    placeholders = parse_jsx_placeholders(content)

    if not placeholders:
        print("  No placeholder images found (looking for image-coming-soon.svg)")
        return {"total": 0, "generated": 0, "failed": 0}

    print(f"  Found {len(placeholders)} placeholder image(s)\n")

    # Show what we found
    for p in placeholders:
        desc_preview = p["description"][:60] + "..." if len(p["description"]) > 60 else p["description"]
        print(f"  [{p['index'] + 1}] {p['tag']} ({p['width']}x{p['height']})")
        print(f"      {desc_preview or '(no description)'}")
    print()

    replacements = []
    generated = 0
    failed = 0
    total_start = time.time()

    for p in placeholders:
        idx = p["index"]
        desc = p["description"]
        w = p["width"]
        h = p["height"]

        if not desc:
            print(f"  [{idx + 1}/{len(placeholders)}] SKIPPED — no description")
            failed += 1
            continue

        print(f"  [{idx + 1}/{len(placeholders)}] Generating: {desc[:60]}...")

        start = time.time()
        try:
            svg_string, metadata = generate_svg(client, desc, config, w, h)
        except (RuntimeError, ValueError) as e:
            print(f"    FAILED: {e}")
            failed += 1
            continue
        elapsed = time.time() - start

        # Extract cached PNG bytes for upload
        cached_png = metadata.pop("_png_bytes", None)

        # Show progress
        v = metadata.get("validation", {})
        v_status = v.get("status", "none")
        v_attempts = v.get("attempts", 1)
        retry_info = f" (retried {v_attempts - 1}x)" if v_attempts > 1 else ""
        print(f"    Done in {elapsed:.1f}s — {v_status}{retry_info}")

        # Save SVG locally
        config.ensure_output_dir()
        safe_name = _sanitize_filename(metadata.get("type", "diagram"))
        filename = f"{safe_name}_{int(time.time())}_{idx}.svg"
        svg_path = config.output_dir / filename
        svg_path.write_text(svg_string, encoding="utf-8")

        # Build replacement DraftImage code
        if upload and config.has_upload_key:
            try:
                upload_result = upload_svg(
                    svg_content=svg_string,
                    width=w,
                    height=h,
                    title=metadata.get("title", "Maths Diagram"),
                    description=metadata.get("accessibility_description", ""),
                    png_bytes=cached_png,
                )
                hosted_url = upload_result["url"]
                host_name = upload_result["host"]
                draft_code = format_draft_image_url(hosted_url, metadata, w, h)
                print(f"    Uploaded to {host_name}: {hosted_url}")
            except Exception as e:
                print(f"    Upload failed: {e} — using placeholder")
                draft_code = format_draft_image(svg_string, metadata, w, h)
        else:
            draft_code = format_draft_image(svg_string, metadata, w, h)

        replacements.append({
            "char_start": p["char_start"],
            "char_end": p["char_end"],
            "new_code": draft_code,
        })
        generated += 1

        # ETA
        elapsed_total = time.time() - total_start
        remaining = len(placeholders) - (idx + 1)
        if generated > 0:
            avg = elapsed_total / generated
            eta = avg * remaining
            print(f"    ETA: ~{eta:.0f}s remaining ({remaining} left)")

    # Apply replacements to JSX
    if replacements:
        modified = apply_jsx_replacements(content, replacements)

        # Determine output path
        if output_dir:
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            out_dir = jsx_file.parent

        out_name = f"{jsx_file.stem}_with_images{jsx_file.suffix}"
        out_path = out_dir / out_name
        out_path.write_text(modified, encoding="utf-8")

        print(f"\n  Output: {out_path}")
    else:
        out_path = None
        print(f"\n  No replacements made.")

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"JSX Processing Summary:")
    print(f"  Placeholders found: {len(placeholders)}")
    print(f"  Generated: {generated}")
    print(f"  Failed/skipped: {failed}")
    print(f"  Total time: {total_elapsed:.1f}s")
    if out_path:
        print(f"  Output file: {out_path}")

    return {
        "total": len(placeholders),
        "generated": generated,
        "failed": failed,
        "output_path": str(out_path) if out_path else None,
        "total_time": round(total_elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Maths SVG Image Generator — generate mathematical diagrams from descriptions"
    )
    parser.add_argument(
        "description",
        nargs="?",
        help="Natural language description of the diagram to generate",
    )
    parser.add_argument(
        "--batch",
        type=str,
        help="Path to a .txt or .json file for batch generation",
    )
    parser.add_argument(
        "--jsx",
        type=str,
        help="Path to a JSX file — finds placeholder images (image-coming-soon.svg) and generates replacements",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output directory for modified JSX file (default: same directory as input)",
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Output filename (without .svg extension)",
    )
    parser.add_argument(
        "--width",
        type=int,
        help="SVG width (default from config)",
    )
    parser.add_argument(
        "--height",
        type=int,
        help="SVG height (default from config)",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to YAML config file (default: project-configs/default.yaml)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload to image host and use HTTPS URL in DraftImage (requires IMGBB_API_KEY in .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SVG and metadata without saving to disk",
    )

    args = parser.parse_args()

    if not args.description and not args.batch and not args.jsx:
        parser.error("Provide a description, --batch file, or --jsx file")

    # Load config
    config = ImageGenConfig(args.config)
    if not config.api_key:
        print("Error: OPENROUTER_API_KEY environment variable not set.")
        sys.exit(1)

    if args.upload and not config.has_upload_key:
        print("Error: No image hosting API key found in .env file.")
        print("Add one of:")
        print("  IMGBB_API_KEY=xxx   (free at https://api.imgbb.com/)")
        print("  IMGUR_CLIENT_ID=xxx (free at https://api.imgur.com/oauth2/addclient)")
        sys.exit(1)

    # Init LLM client
    client = LLMClient(api_key=config.api_key, max_retries=config.max_retries)

    print(f"Maths SVG Image Generator")
    print(f"Model: {config.model}")
    if args.upload:
        host = "imgbb" if config.imgbb_api_key else "imgur"
        print(f"Upload: {host} (HTTPS URLs)")

    start_time = time.time()

    if args.jsx:
        # JSX processing mode — has its own summary
        jsx_result = _run_jsx(client, args.jsx, config, args.upload, args.output)

        # Print LLM usage
        usage = client.get_usage_summary()
        print(f"  LLM calls: {usage['total_calls']}")
        print(f"  Tokens: {usage['total_input_tokens']:,} in / {usage['total_output_tokens']:,} out")
        return

    if args.batch:
        results = _run_batch(
            client, args.batch, config, args.width, args.height, args.dry_run, args.upload
        )
    else:
        result = _generate_single(
            client, args.description, config, args.name, args.width, args.height,
            args.dry_run, args.upload,
        )
        results = [result] if result else []

    # Summary
    total_time = time.time() - start_time
    usage = client.get_usage_summary()
    saved_count = sum(1 for r in results if r.get("saved"))
    uploaded_count = sum(1 for r in results if r.get("hosted_url"))

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Generated: {len(results)} diagram(s)")
    print(f"  Saved: {saved_count} file(s)")
    if args.upload:
        print(f"  Uploaded: {uploaded_count}")
    print(f"  Total time: {total_time:.1f}s")
    print(f"  LLM calls: {usage['total_calls']}")
    print(f"  Tokens: {usage['total_input_tokens']:,} in / {usage['total_output_tokens']:,} out")


if __name__ == "__main__":
    main()

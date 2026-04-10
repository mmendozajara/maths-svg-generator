"""Build a consolidated image catalogue from gold standard catalogue TSV files.

Reads all catalogue_images.tsv files from the gold standard catalogue outputs
and consolidates them into a single searchable JSON catalogue.

Usage:
    python build_image_catalogue.py
    python build_image_catalogue.py --catalogue-dir /path/to/outputs --output catalogue.json
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path


def build_catalogue(catalogue_dir: Path) -> list[dict]:
    """Scan all catalogue_images.tsv files and extract image entries.

    Returns a list of image dicts with normalised fields.
    """
    entries = []
    tsv_files = sorted(catalogue_dir.glob("*/catalogue_images.tsv"))

    if not tsv_files:
        print(f"No catalogue_images.tsv files found in {catalogue_dir}")
        return []

    print(f"Found {len(tsv_files)} catalogue files to process")

    for tsv_path in tsv_files:
        book_id = tsv_path.parent.name
        count = 0
        skipped = 0

        with open(tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                desc = (row.get("accessibility_description") or "").strip()

                # Skip images without descriptions — can't match on them
                if not desc or desc.lower() in ("", "n/a", "none"):
                    skipped += 1
                    continue

                # Parse dimensions
                try:
                    width = int(row.get("width", 260))
                except (ValueError, TypeError):
                    width = 260
                try:
                    height = int(row.get("height", 260))
                except (ValueError, TypeError):
                    height = 260

                entry = {
                    "description": desc,
                    "image_url": row.get("full_image_url", ""),
                    "image_path": row.get("image_path", ""),
                    "image_format": row.get("image_format", "svg"),
                    "width": width,
                    "height": height,
                    "source_book": row.get("textbook_id", book_id),
                    "curriculum": row.get("curriculum", ""),
                    "year_level": row.get("year_level", ""),
                    "book_title": row.get("book_title", ""),
                    "subtopic_id": row.get("subtopic_id", ""),
                    "source_file": row.get("source_file", ""),
                    "idea_title": row.get("idea_title", ""),
                }

                # Only include entries with a usable URL
                if entry["image_url"] or entry["image_path"]:
                    entries.append(entry)
                    count += 1
                else:
                    skipped += 1

        print(f"  Book {book_id}: {count} images ({skipped} skipped — no description or URL)")

    return entries


def deduplicate(entries: list[dict]) -> list[dict]:
    """Remove duplicate images (same URL or same description + dimensions)."""
    seen_urls = set()
    seen_desc = set()
    unique = []

    for entry in entries:
        url = entry.get("image_url", "")
        desc_key = (entry["description"].lower().strip(), entry["width"], entry["height"])

        if url and url in seen_urls:
            continue
        if desc_key in seen_desc:
            continue

        if url:
            seen_urls.add(url)
        seen_desc.add(desc_key)
        unique.append(entry)

    return unique


def main():
    parser = argparse.ArgumentParser(description="Build consolidated image catalogue from gold standard TSVs")
    parser.add_argument(
        "--catalogue-dir",
        type=str,
        default=str(Path(__file__).resolve().parent.parent.parent / "gold-standard-catalogue" / "gold-standard-catalogue" / "outputs"),
        help="Path to gold standard catalogue outputs directory",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path(__file__).resolve().parent / "image_catalogue.json"),
        help="Output JSON file path",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Skip deduplication",
    )
    args = parser.parse_args()

    catalogue_dir = Path(args.catalogue_dir)
    if not catalogue_dir.is_dir():
        print(f"Error: Catalogue directory not found: {catalogue_dir}")
        sys.exit(1)

    print(f"Building image catalogue from: {catalogue_dir}")
    start = time.time()

    entries = build_catalogue(catalogue_dir)

    if not entries:
        print("No images found.")
        sys.exit(1)

    print(f"\nTotal images extracted: {len(entries):,}")

    if not args.no_dedup:
        before = len(entries)
        entries = deduplicate(entries)
        removed = before - len(entries)
        print(f"After deduplication: {len(entries):,} ({removed:,} duplicates removed)")

    # Write output
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "version": 1,
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_images": len(entries),
            "images": entries,
        }, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\nCatalogue written to: {output_path}")
    print(f"  {len(entries):,} images, {size_mb:.1f} MB, built in {elapsed:.1f}s")


if __name__ == "__main__":
    main()

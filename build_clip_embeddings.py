"""Build CLIP image embeddings for the image catalogue.

Downloads each SVG from the catalogue, renders to PNG via Playwright,
computes CLIP embeddings, and saves to a .npz file.
No images are saved to disk.

Usage:
    python build_clip_embeddings.py
    python build_clip_embeddings.py --batch-size 64
"""

import argparse
import json
import sys
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from sentence_transformers import SentenceTransformer


def render_svg_to_pil(page, svg_content: str, size: int = 224) -> Image.Image | None:
    """Render SVG content to a PIL Image using an existing Playwright page."""
    try:
        html = f'<html><body style="margin:0;padding:0;background:white;display:flex;align-items:center;justify-content:center;width:{size}px;height:{size}px">{svg_content}</body></html>'
        page.set_content(html, wait_until="load")
        png_bytes = page.screenshot(type="png")
        return Image.open(BytesIO(png_bytes)).convert("RGB")
    except Exception:
        return None


def download_svg(url: str, timeout: int = 10) -> str | None:
    """Download SVG content from URL, return as string or None on failure."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        # Only accept SVG/XML content
        if "svg" in content_type or "xml" in content_type or resp.content[:5] == b"<svg " or resp.content[:5] == b"<?xml":
            return resp.content.decode("utf-8", errors="replace")
        # Try PNG/JPEG directly
        try:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            return img  # Return PIL image directly
        except Exception:
            return None
    except Exception:
        return None


def build_embeddings(
    catalogue_path: Path,
    model_name: str = "clip-ViT-B-32",
    batch_size: int = 32,
    render_size: int = 224,
) -> tuple[np.ndarray, list[int]]:
    """Download SVGs, render to PNG, compute CLIP embeddings."""
    from playwright.sync_api import sync_playwright

    with open(catalogue_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    images_meta = data.get("images", [])
    total = len(images_meta)
    print(f"Catalogue has {total:,} images")

    # Load CLIP model
    print(f"Loading CLIP model: {model_name}...")
    model = SentenceTransformer(model_name)
    print(f"  Model loaded")

    # Start persistent browser
    print(f"Starting Playwright browser...")
    pw = sync_playwright().start()
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": render_size, "height": render_size})
    print(f"  Browser ready")

    all_embeddings = []
    valid_indices = []
    failed = 0
    batch_images = []
    batch_indices = []

    start = time.time()

    for i, entry in enumerate(images_meta):
        url = entry.get("image_url", "")
        if not url:
            failed += 1
            continue

        # Download
        result = download_svg(url)
        if result is None:
            failed += 1
        elif isinstance(result, Image.Image):
            # Already a PIL image (PNG/JPEG)
            batch_images.append(result.resize((render_size, render_size)))
            batch_indices.append(i)
        else:
            # SVG string — render via Playwright
            img = render_svg_to_pil(page, result, render_size)
            if img is None:
                failed += 1
            else:
                batch_images.append(img)
                batch_indices.append(i)

        # Process batch when full
        if len(batch_images) >= batch_size:
            embeddings = model.encode(batch_images, batch_size=batch_size, show_progress_bar=False)
            all_embeddings.append(embeddings)
            valid_indices.extend(batch_indices)
            for im in batch_images:
                im.close()
            batch_images = []
            batch_indices = []

        if (i + 1) % 50 == 0 or i == total - 1:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total - i - 1) / rate if rate > 0 else 0
            ok = len(valid_indices) + len(batch_images)
            print(f"  [{i + 1}/{total}] {ok} ok, {failed} failed | {rate:.1f} img/s | ETA: {eta:.0f}s")

    # Process remaining batch
    if batch_images:
        embeddings = model.encode(batch_images, batch_size=batch_size, show_progress_bar=False)
        all_embeddings.append(embeddings)
        valid_indices.extend(batch_indices)
        for im in batch_images:
            im.close()

    # Cleanup browser
    browser.close()
    pw.stop()

    if not all_embeddings:
        print("No images could be processed.")
        return np.array([]), []

    combined = np.vstack(all_embeddings).astype(np.float32)

    # Normalize for cosine similarity
    norms = np.linalg.norm(combined, axis=1, keepdims=True)
    norms[norms == 0] = 1
    combined = combined / norms

    return combined, valid_indices


def main():
    parser = argparse.ArgumentParser(description="Build CLIP embeddings for image catalogue")
    parser.add_argument(
        "--catalogue",
        type=str,
        default=str(Path(__file__).resolve().parent / "image_catalogue.json"),
        help="Path to image_catalogue.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path(__file__).resolve().parent / "clip_embeddings.npz"),
        help="Output .npz file path",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="clip-ViT-B-32",
        help="CLIP model name (default: clip-ViT-B-32)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for CLIP encoding (default: 32)",
    )
    args = parser.parse_args()

    catalogue_path = Path(args.catalogue)
    if not catalogue_path.exists():
        print(f"Error: Catalogue not found at {catalogue_path}")
        print("Run: python build_image_catalogue.py")
        sys.exit(1)

    print(f"Building CLIP embeddings")
    print(f"  Catalogue: {catalogue_path}")
    print(f"  Model: {args.model}")
    print(f"  Batch size: {args.batch_size}")
    print()

    start = time.time()
    embeddings, valid_indices = build_embeddings(
        catalogue_path,
        model_name=args.model,
        batch_size=args.batch_size,
    )

    if len(valid_indices) == 0:
        print("No embeddings computed.")
        sys.exit(1)

    # Save embeddings + index mapping
    output_path = Path(args.output)
    np.savez_compressed(
        output_path,
        embeddings=embeddings,
        valid_indices=np.array(valid_indices, dtype=np.int32),
    )

    elapsed = time.time() - start
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\nDone!")
    print(f"  Embeddings: {embeddings.shape[0]:,} images x {embeddings.shape[1]} dims")
    print(f"  Saved to: {output_path} ({size_mb:.1f} MB)")
    print(f"  Total time: {elapsed:.0f}s")


if __name__ == "__main__":
    main()

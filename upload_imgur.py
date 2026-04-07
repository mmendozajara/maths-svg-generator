"""Upload SVG images as PNG to image hosting and return HTTPS URLs.

Supports two hosting backends:
    - imgbb (default) — free, generous limits, simple API
    - imgur — free but stricter rate limits on new accounts

Workflow: SVG string -> PNG (via headless Chromium) -> upload -> HTTPS URL (.jpg)

Requirements:
    pip install playwright requests
    python -m playwright install chromium
"""

import atexit
import base64
import os
import tempfile
import threading
from pathlib import Path

import requests as http_requests  # avoid shadowing


# ---------------------------------------------------------------------------
# Persistent Chromium browser (thread-local to avoid Playwright thread issues)
# ---------------------------------------------------------------------------
_thread_local = threading.local()


def _get_browser():
    """Return a persistent Chromium browser for the current thread.

    Playwright's sync API binds to the thread that created it.  We keep one
    browser per thread so Flask / ThreadPoolExecutor workers each get their
    own long-lived instance without cross-thread errors.
    """
    browser = getattr(_thread_local, "browser", None)
    pw = getattr(_thread_local, "playwright", None)

    if browser is None or not browser.is_connected():
        # Clean up stale handles first
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if pw:
                pw.stop()
        except Exception:
            pass

        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        _thread_local.playwright = pw
        _thread_local.browser = browser
        atexit.register(_shutdown_browser_thread, pw, browser)

    return browser


def _shutdown_browser_thread(pw, browser):
    """Clean up a specific browser/playwright pair on process exit."""
    try:
        if browser:
            browser.close()
    except Exception:
        pass
    try:
        if pw:
            pw.stop()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SVG → PNG via Playwright (headless Chromium)
# ---------------------------------------------------------------------------
def svg_to_png(svg_content: str, width: int = 260, height: int = 260) -> bytes:
    """Convert an SVG string to PNG bytes using headless Chromium.

    Renders the SVG in a browser page at exact dimensions, then screenshots.
    Uses a persistent browser instance to avoid cold-start overhead.
    """
    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8"
    )
    try:
        html = f"""<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.css">
<style>
  html, body {{ margin: 0; padding: 0; width: {width}px; height: {height}px; background: white; overflow: hidden; }}
  svg {{ display: block; width: {width}px; height: {height}px; }}
</style></head>
<body>
{svg_content}
</body>
</html>"""
        tmp.write(html)
        tmp.close()

        browser = _get_browser()
        page = browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=2,  # 2x for crisp rendering
        )
        try:
            page.goto(f"file:///{tmp.name.replace(os.sep, '/')}")
            page.wait_for_load_state("networkidle")

            png_bytes = page.screenshot(
                clip={"x": 0, "y": 0, "width": width, "height": height},
                type="png",
            )
        finally:
            page.close()

        return png_bytes
    finally:
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# imgbb upload (default)
# ---------------------------------------------------------------------------
IMGBB_API_URL = "https://api.imgbb.com/1/upload"


def upload_to_imgbb(
    image_bytes: bytes,
    api_key: str,
    name: str | None = None,
) -> dict:
    """Upload image bytes to imgbb.

    Returns response data dict with:
        - url: page URL
        - display_url: direct image URL
        - thumb: thumbnail URLs
    """
    b64_image = base64.b64encode(image_bytes).decode("ascii")

    payload = {"key": api_key, "image": b64_image}
    if name:
        payload["name"] = name

    resp = http_requests.post(IMGBB_API_URL, data=payload, timeout=60)
    resp.raise_for_status()

    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"imgbb upload failed: {body}")

    return body["data"]


# ---------------------------------------------------------------------------
# Imgur upload (alternative)
# ---------------------------------------------------------------------------
IMGUR_API_URL = "https://api.imgur.com/3/image"


def upload_to_imgur(
    image_bytes: bytes,
    client_id: str,
    title: str | None = None,
    description: str | None = None,
) -> dict:
    """Upload image bytes to Imgur.

    Returns response data dict with:
        - link: direct URL (e.g. https://i.imgur.com/XXXXX.png)
        - id: image ID
        - deletehash: for anonymous deletion later
    """
    b64_image = base64.b64encode(image_bytes).decode("ascii")

    headers = {"Authorization": f"Client-ID {client_id}"}
    payload = {"image": b64_image, "type": "base64"}
    if title:
        payload["title"] = title
    if description:
        payload["description"] = description

    resp = http_requests.post(IMGUR_API_URL, headers=headers, data=payload, timeout=60)
    resp.raise_for_status()

    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"Imgur upload failed: {body}")

    return body["data"]


# ---------------------------------------------------------------------------
# Unified upload function
# ---------------------------------------------------------------------------
def upload_svg(
    svg_content: str,
    width: int = 260,
    height: int = 260,
    title: str | None = None,
    description: str | None = None,
    host: str | None = None,
    png_bytes: bytes | None = None,
) -> dict:
    """Full pipeline: SVG string → PNG → image host → result dict.

    Auto-detects host based on which API key is set in .env:
        - IMGBB_API_KEY → uses imgbb (preferred)
        - IMGUR_CLIENT_ID → uses imgur (fallback)

    Override with host="imgbb" or host="imgur".

    If png_bytes is provided, skips the SVG→PNG render step (saves ~3-5s).

    Returns dict with:
        - url: HTTPS URL with .jpg extension (for DraftImage)
        - host: which service was used
        - delete_url: deletion URL if available
        - original_link: original URL from the service
    """
    imgbb_key = os.environ.get("IMGBB_API_KEY", "")
    imgur_id = os.environ.get("IMGUR_CLIENT_ID", "")

    # Auto-detect host
    if host is None:
        if imgbb_key:
            host = "imgbb"
        elif imgur_id:
            host = "imgur"
        else:
            raise ValueError(
                "No image hosting API key found. Add one to your .env file:\n"
                "  IMGBB_API_KEY=xxx   (free at https://api.imgbb.com/)\n"
                "  IMGUR_CLIENT_ID=xxx  (free at https://api.imgur.com/oauth2/addclient)"
            )

    # Step 1: SVG → PNG (skip if pre-rendered PNG provided)
    if png_bytes is None:
        png_bytes = svg_to_png(svg_content, width, height)

    # Step 2: Upload
    if host == "imgbb":
        if not imgbb_key:
            raise ValueError("IMGBB_API_KEY not set in .env")
        data = upload_to_imgbb(png_bytes, imgbb_key, name=title)

        original_link = data["image"]["url"]
        # Force .jpg extension for DraftImage
        base_url = original_link.rsplit(".", 1)[0]
        jpg_url = f"{base_url}.jpg"

        return {
            "url": jpg_url,
            "host": "imgbb",
            "original_link": original_link,
            "page_url": data.get("url_viewer", ""),
            "delete_url": data.get("delete_url", ""),
        }

    elif host == "imgur":
        if not imgur_id:
            raise ValueError("IMGUR_CLIENT_ID not set in .env")
        data = upload_to_imgur(png_bytes, imgur_id, title, description)

        original_link = data["link"]
        base_url = original_link.rsplit(".", 1)[0]
        jpg_url = f"{base_url}.jpg"

        return {
            "url": jpg_url,
            "host": "imgur",
            "original_link": original_link,
            "imgur_id": data.get("id", ""),
            "delete_hash": data.get("deletehash", ""),
        }

    else:
        raise ValueError(f"Unknown host: {host}. Use 'imgbb' or 'imgur'.")


# ---------------------------------------------------------------------------
# CLI for standalone testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")

    parser = argparse.ArgumentParser(description="Upload an SVG file to image hosting")
    parser.add_argument("svg_file", help="Path to SVG file")
    parser.add_argument("--width", type=int, default=260)
    parser.add_argument("--height", type=int, default=260)
    parser.add_argument("--host", choices=["imgbb", "imgur"], help="Force a specific host")
    args = parser.parse_args()

    svg_path = Path(args.svg_file)
    svg_content = svg_path.read_text(encoding="utf-8")

    print(f"Converting {svg_path.name} to PNG ({args.width}x{args.height})...")
    result = upload_svg(svg_content, width=args.width, height=args.height, host=args.host)

    print(f"\n  Host:          {result['host']}")
    print(f"  URL (.jpg):    {result['url']}")
    print(f"  Original link: {result['original_link']}")
    if result.get("delete_url"):
        print(f"  Delete URL:    {result['delete_url']}")

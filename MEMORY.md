# CLAUDE.md — Maths SVG Image Generator

## Project Overview

LLM-powered tool that generates mathematical diagrams as SVG from natural language descriptions. Outputs production-ready `<DraftImage>` JSX snippets with hosted HTTPS URLs. Styled with Figma design tokens, validated by vision LLM.

**Stack:** Python, Flask, Playwright (headless Chromium), OpenRouter API (Claude Sonnet 4.5), imgbb image hosting.

## Architecture

```
Description → LLM (SVG generation) → XML validation → PNG render (Chromium)
→ Vision LLM validation → auto-retry if issues → PNG upload (imgbb) → <DraftImage> JSX
```

### Core Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web server with REST API. 3 tabs: Single, Batch, JSX Processor. `--share` flag for ngrok |
| `generate.py` | CLI entry point. Modes: single description, `--batch` (TXT/JSON), `--jsx` (JSX file processing) |
| `svg_generator.py` | LLM SVG generation + XML validation + image validation loop. Returns cached PNG bytes |
| `validate_image.py` | Vision LLM — checks cutoff/clipping + mathematical accuracy |
| `jsx_embed.py` | `format_draft_image()` / `format_draft_image_url()` for JSX output. `parse_jsx_placeholders()` + `apply_jsx_replacements()` for JSX file processing |
| `upload_imgur.py` | SVG→PNG via persistent Chromium + upload to imgbb/Imgur. Thread-safe via `threading.local()` |
| `llm_client.py` | Thread-safe OpenRouter API client (text + vision). `threading.Lock` on usage counters |
| `config.py` | YAML config + `.env` loader |
| `sync_figma_styles.py` | Pulls design tokens from Figma REST API → updates `default.yaml` |

### Prompts

| File | Purpose |
|------|---------|
| `prompts/svg_system.md` | System prompt with Figma style guide, per-diagram-type guidelines, quality rules, examples |
| `prompts/validate_image.md` | Vision validation prompt — cutoff detection + math accuracy checks |

### Config

| File | Purpose |
|------|---------|
| `project-configs/default.yaml` | Models, LLM settings, default dimensions, Figma colour palette, stroke rules, font rules |
| `.env` | API keys: `OPENROUTER_API_KEY`, `IMGBB_API_KEY`, `NGROK_AUTH_TOKEN` (optional), `FIGMA_API_TOKEN` (optional) |

## Figma Design Tokens (Current)

| Token | Value | Usage |
|-------|-------|-------|
| Primary | `#25374B` (Cloudburst) | Main text, strokes, labels, outlines |
| Blue | `#0875BE` | Highlighted/emphasised elements, marked points |
| Teal | `#ACE3D9` | Filled/shaded regions (only when description says shaded/filled) |
| Gray | `#5E6D7F` | Secondary descriptive text |
| Grid | `#E5E6E8` | Grid lines |
| Font | Proxima Nova | All text |
| Math Font | KaTeX_Main | Mathematical variables (italic) |
| Standard stroke | 3px | Shape outlines, axes |
| Labelling stroke | 2px | Dimension lines, annotations, dashes |
| Stroke caps/joins | round | All strokes |

**Important:** Regular 2D shapes (triangles, polygons) use `fill="none"` by default. Only fill with teal when description explicitly mentions shading/area/filled.

## Key Patterns

### Thread-safe Playwright
`upload_imgur.py` uses `threading.local()` for per-thread Chromium browser instances. This is required because Flask request handlers run on different threads and Playwright's sync API binds to the creating thread.

### PNG Reuse
The PNG rendered during validation is cached in `metadata["_png_bytes"]` and passed to the upload step to avoid re-rendering.

### JSX Placeholder Processing
`jsx_embed.py` finds `<DraftImage>` or `<Image>` tags with `image-coming-soon.svg` in path/url/src. Extracts `accessibilityDescription` as the generation prompt. Replacements applied in reverse position order to avoid offset drift.

### Image Validation Loop
`svg_generator.py` runs a generate→validate→retry loop (up to 3 retries). Vision LLM checks for cutoff/clipping and mathematical accuracy. Fix instructions from failed validation are fed back to the generator.

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Web UI |
| `/api/generate` | POST | Generate single SVG from description |
| `/api/jsx/parse` | POST | Parse JSX file, return placeholder list |
| `/api/jsx/build` | POST | Apply replacements to JSX, return modified file |

## Diagram Types

Number lines, coordinate graphs, geometry (triangles, angles, polygons), bar charts, pie charts, fraction diagrams (bar models, area models, circle sectors).

## Deployment

- **Railway** (recommended): Auto-deploys from GitHub via Dockerfile
- **Docker**: `docker build -t maths-svg-generator .` + `docker run`
- **ngrok**: `python app.py --share` for quick public URL
- **Local**: `python app.py` at `http://localhost:5000`

## Known Issues / Gotchas

- Detailed 2D shape style rules (e.g., teal right-angle markers) caused the LLM to incorrectly place markers on non-90-degree angles. Keep geometric shape rules simple.
- Flask template changes require server restart (no hot-reload for Jinja templates).
- The `--share` flag requires `NGROK_AUTH_TOKEN` in `.env`.

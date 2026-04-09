# CLAUDE.md — Maths SVG Image Generator

## Project Overview

LLM-powered tool that generates mathematical diagrams as SVG from natural language descriptions. Outputs production-ready `<DraftImage>` JSX snippets with hosted HTTPS URLs. Optional Figma design token styling (off by default), validated by vision LLM.

**Stack:** Python, Flask, Playwright (headless Chromium), OpenRouter API (Gemini 3.1 Pro + Claude Sonnet 4.5), imgbb image hosting.

## Architecture

```
Description → LLM (SVG generation) → XML validation → PNG render (Chromium)
→ Vision LLM validation → show issues + Retry button → PNG upload (async, imgbb) → <DraftImage> JSX
```

### Core Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web server with REST API. 3 tabs: Single, Batch, JSX Processor. `/api/validate` for on-demand validation. `--share` flag for ngrok |
| `generate.py` | CLI entry point. Modes: single description, `--batch` (TXT/JSON), `--jsx` (JSX file processing) |
| `svg_generator.py` | LLM SVG generation + XML validation + image validation loop. Supports Figma/generic style guide toggle. Returns cached PNG bytes |
| `validate_image.py` | Vision LLM — checks cutoff/clipping + mathematical accuracy |
| `jsx_embed.py` | `format_draft_image()` / `format_draft_image_url()` for JSX output. `parse_jsx_placeholders()` + `apply_jsx_replacements()` for JSX file processing |
| `upload_imgur.py` | SVG→PNG via persistent Chromium + upload to imgbb/Imgur. Thread-safe via `threading.local()` |
| `llm_client.py` | Thread-safe OpenRouter API client (text + vision + thinking budget control). `threading.Lock` on usage counters. Prompt caching via `cache_control` |
| `config.py` | YAML config + `.env` loader. `get_styling_block()` + `get_style_guide_block()` for conditional Figma/generic styling |
| `sync_figma_styles.py` | Pulls design tokens from Figma REST API → updates `default.yaml` |

### Prompts

| File | Purpose |
|------|---------|
| `prompts/svg_system.md` | System prompt template with `{{STYLING}}` + `{{STYLE_GUIDE}}` placeholders |
| `prompts/style_guide_figma.md` | Figma brand style guide — colours, fonts, strokes, 2 SVG examples |
| `prompts/style_guide_generic.md` | Clean generic style guide — no hardcoded brand values |
| `prompts/validate_image.md` | Vision validation prompt — cutoff detection + math accuracy checks |

### Config

| File | Purpose |
|------|---------|
| `project-configs/default.yaml` | Models, LLM settings (incl. `thinking_budget: 0`), default dimensions, Figma colour palette, stroke rules, font rules |
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

### Figma Styling Toggle
`svg_generator.py` calls `config.get_styling_block(use_figma)` and `config.get_style_guide_block(use_figma)` to conditionally load brand or generic styling. The web UI has a "Use Figma Styling" checkbox (unchecked by default) in all 3 tabs.

### Thinking Budget
`llm_client.py` supports `thinking_budget` parameter: `0` = disabled (default, fastest), positive int = cap, `None` = uncapped. Set in `default.yaml` under `llm.thinking_budget`.

### Image Validation (No Auto-Retry)
`svg_generator.py` generates SVG then optionally validates via vision LLM (cutoff/clipping, mathematical accuracy, mathematical consistency). With `image_validation_retries: 0` (default), auto-validation is skipped but users can click the **Validate** button on any result card. Manual retry sends fix instructions back to the generator.

### Parallel Upload
`app.py` returns the SVG immediately to the frontend. PNG upload to imgbb runs in a background daemon thread. The frontend polls `/api/upload-status/<upload_id>` every 2s to get the hosted URL when ready. Upload status indicators show uploading/uploaded/error state on each card.

### Prompt Caching
`llm_client.py` uses `cache_control: {"type": "ephemeral"}` on system prompt content blocks for OpenRouter prompt caching (~75% savings on cached reads).

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Web UI |
| `/api/generate` | POST | Generate single SVG. Accepts `use_figma_styling` (default: false) |
| `/api/validate` | POST | On-demand vision validation. Body: `{svg, description, width, height}` |
| `/api/upload-status/<id>` | GET | Poll background upload status |
| `/api/batch` | POST | Batch generate multiple SVGs |
| `/api/batch/download` | POST | Download batch results as ZIP |
| `/api/jsx/parse` | POST | Parse JSX file, return placeholder list |
| `/api/jsx/build` | POST | Apply replacements to JSX, return modified file |

## Diagram Types

Number lines, coordinate graphs, geometry (triangles, angles, polygons), bar charts, pie charts, fraction diagrams (bar models, area models, circle sectors).

## Deployment

- **Render** (current): Auto-deploys from GitHub (maths-svg-generator repo) via Dockerfile
- **Docker**: `docker build -t maths-svg-generator .` + `docker run`
- **ngrok**: `python app.py --share` for quick public URL
- **Local**: `python app.py` at `http://localhost:5000`

## Models (Current)

| Role | Model | Notes |
|------|-------|-------|
| SVG Generator | `google/gemini-3.1-pro-preview-20260219` | Thinking model — thinking disabled by default (`thinking_budget: 0`). Needs max_tokens=32768 |
| Image Validator | `anthropic/claude-sonnet-4-5` | Vision model — fewer false positives than Flash/Haiku |

## Known Issues / Gotchas

- Gemini 3.1 Pro is a "thinking" model — it uses ~7000+ reasoning tokens internally. With max_tokens too low (e.g., 8192), visible output gets truncated and SVG extraction fails. Keep max_tokens at 32768.
- Detailed 2D shape style rules (e.g., teal right-angle markers) caused the LLM to incorrectly place markers on non-90-degree angles. Keep geometric shape rules simple.
- Flask template changes require server restart (no hot-reload for Jinja templates).
- The `--share` flag requires `NGROK_AUTH_TOKEN` in `.env`.
- gunicorn workers don't execute `if __name__ == "__main__"` — module-level `_init()` call with guard is required in `app.py`.

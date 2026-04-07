# Project Brief: Maths SVG Image Generator

## Overview

| Field | Detail |
|-------|--------|
| **Project** | Maths SVG Image Generator |
| **Purpose** | Generate mathematical diagrams as SVG from natural language, styled with Figma design tokens, validated by vision LLM, hosted as HTTPS URLs for embedding in JSX content |
| **Team** | Content Production — UK National |
| **Status** | MVP Complete |
| **Created** | 2026-03-31 |

## Problem Statement

Content authors need mathematical diagrams (number lines, graphs, geometry, charts) embedded in JSX lesson files as `<DraftImage>` components. Currently this requires:

1. Manual creation in a design tool (Figma, Illustrator)
2. Export and upload to image hosting
3. Copy the URL into JSX code
4. Write accessibility descriptions manually

This is slow (~15-30 min per diagram) and inconsistent in styling.

## Solution

An LLM-powered tool that takes a plain English description and produces a ready-to-paste `<DraftImage>` JSX snippet in ~30-90 seconds, with:

- SVG matching the Figma design system (colours, fonts, spacing)
- **Image validation** (cutoff detection + mathematical accuracy + mathematical consistency via vision LLM)
- **No auto-retry** — validation runs once; if issues found, user sees them and decides whether to retry
- **Manual retry** button on result cards with issues (sends fix instructions back to LLM)
- Automatic upload to image hosting (HTTPS URL)
- Auto-generated accessibility descriptions
- Web interface with progress tracking, cancel, and batch downloads
- CLI for single + batch processing (TXT and JSON) + JSX file processing
- **JSX file processing** — upload a JSX file with `image-coming-soon.svg` placeholders, auto-generates all images and outputs the modified JSX
- **Persistent Chromium browser** for fast SVG-to-PNG rendering (no cold-start per render)
- **PNG reuse** from validation to upload (eliminates redundant re-render)
- **Parallel upload** — SVG returned immediately; PNG upload runs in background thread
- **Prompt caching** — system prompt cached via OpenRouter (~75% savings on cached reads)

## Architecture

```
                                +-----------------+
  User description ----------> |  Flask Web UI   |
  (or CLI / batch TXT/JSON     |  or CLI         |
   or JSX file with            |                 |
   placeholder images)         +--------+--------+
                                         |
                                         v
                                +-----------------+
                                |  SVG Generator   |
                                |  (LLM call via   |
                                |   OpenRouter)    |
                                +--------+--------+
                                         |
                           System prompt populated with
                           Figma design tokens from YAML
                                         |
                                         v
                                +-----------------+
                                |  XML Validator   |
                                |  (parse check)   |
                                +--------+--------+
                                         |
                              Retry if invalid XML
                                         |
                                         v
                                +-----------------+
                                |  PNG Converter   |
                                |  (Persistent     |
                                |   Chromium)      |
                                +--------+--------+
                                         |
                                         v
                                +-----------------+
                                |  Image Validator |
                                |  (Vision LLM)   |
                                |  Cutoff + Math   |
                                +--------+--------+
                                         |
                              If FAIL: regenerate with
                              fix instructions (up to 3x)
                                         |
                              If issues remain: manual
                              Retry button in web UI
                                         |
                                         v
                                +-----------------+
                                |  Image Upload    |
                                |  (imgbb API)     |
                                |  PNG reused from  |
                                |  validation step  |
                                +--------+--------+
                                         |
                                         v
                                +-----------------+
                                |  JSX Formatter   |
                                |  <DraftImage>    |
                                +--------+--------+
                                         |
                              (If JSX input mode)
                                         |
                                         v
                                +-----------------+
                                |  JSX Replacer    |
                                |  Replace         |
                                |  placeholders in |
                                |  original file   |
                                +-----------------+
```

## Components

### Core Pipeline

| Component | File | Description |
|-----------|------|-------------|
| LLM Client | `llm_client.py` | Thread-safe OpenRouter API client with retry logic + vision support + prompt caching |
| SVG Generator | `svg_generator.py` | Calls LLM, extracts SVG + metadata, validates XML, runs image validation loop, returns cached PNG bytes |
| Image Validator | `validate_image.py` | Sends PNG to vision LLM, checks cutoff and mathematical accuracy |
| JSX Formatter | `jsx_embed.py` | Formats `<DraftImage>` JSX with HTTPS URL or placeholder; parses JSX files for placeholder images; applies replacements to JSX content |
| Image Upload | `upload_imgur.py` | Persistent Chromium browser, SVG to PNG, upload to imgbb/Imgur. Accepts pre-rendered PNG to skip re-render |
| Config | `config.py` | Loads YAML config + environment variables |

### Interfaces

| Interface | File | Description |
|-----------|------|-------------|
| Web UI | `app.py` + `templates/index.html` | Flask app with single/batch/JSX processor tabs, progress bar with ETA, cancel, batch downloads, manual retry, parallel upload polling. `--share` flag for ngrok, respects `PORT` env var for cloud deployment |
| CLI | `generate.py` | Single + batch (TXT/JSON) + JSX file processing with `--upload` flag |

### Supporting

| Component | File | Description |
|-----------|------|-------------|
| Figma Sync | `sync_figma_styles.py` | Pulls design tokens from Figma REST API, updates YAML |
| System Prompt | `prompts/svg_system.md` | Detailed LLM instructions for each diagram type |
| Validation Prompt | `prompts/validate_image.md` | Vision validation checklist (cutoff + math accuracy + mathematical consistency) |
| Config | `project-configs/default.yaml` | Colours, fonts, model, dimensions, retry settings |
| Dockerfile | `Dockerfile` | Production container with Chromium + gunicorn (for Railway/Docker deployment) |
| Setup Guide | `SETUP.md` | Step-by-step instructions for coworkers |
| Env Template | `.env.example` | Template listing required API keys |

## Web UI Features

| Feature | Description |
|---------|-------------|
| Single generation | Type description, set dimensions, generate with live preview and ETA |
| Batch generation | Upload .txt file or type manually, sequential processing with ETA |
| JSX processing | Upload .jsx file with placeholder images, generate all, download modified JSX |
| File upload zone | Drag-and-drop .txt files (batch) or .jsx files (JSX processor) |
| Progress bar | Inline progress with live MM:SS timer, item counter, and ETA |
| Cancel | Stop batch/JSX processing mid-way (completes current item gracefully) |
| Retry indication | Progress bar shows when validation triggered retries |
| Manual retry | Orange Retry button on cards with validation issues; sends fix instructions to LLM for regeneration with loading overlay and timer. No auto-retry — user decides |
| Validation badges | Green (passed), red (issues), yellow (skipped) per result |
| Batch downloads | Download SVGs (.zip), Download Codes (.txt), Copy All |
| JSX download | Download Modified JSX button after JSX processing completes |
| Upload toggle | When off, DraftImage uses `url="upload this image first"` |

## Diagram Types Supported

| Type | Key Features |
|------|-------------|
| Number Lines | Horizontal axis, tick marks, labelled integers, marked points as coloured circles |
| Coordinate Graphs | X/Y axes with arrows, optional grid, plotted functions (polylines), legends |
| Geometry | Vertex labels (A, B, C), side length annotations, right-angle markers, angle arcs |
| Bar Charts | Vertical/horizontal bars, category labels, value labels, cycling colours |
| Pie Charts | Coloured sectors, percentage labels with leader lines |
| Fractions | Bar models (divided/shaded), area models, circle sectors |

## Image Validation

The vision-based validation checks every generated diagram:

### Check 1: Cutoff / Clipping
- Text labels not truncated at edges
- Lines/arrows don't disappear at boundaries
- Sufficient padding (minimum ~20px margin)
- No text overlapping other text

### Check 2: Mathematical Accuracy
- Correct diagram type
- All values, labels, and specified elements present
- Mathematically correct curve shapes (parabolas, cubics, sine waves, etc.)
- Correct angles and proportions for geometry
- Consistent axis scales
- **Mathematical consistency** — verifies numeric values are consistent with stated properties (e.g., Pythagoras for right triangles, angle sums = 180°, pie chart % = 100%)

On failure, the validator returns structured fix instructions. The user sees the issues and a Retry button — no auto-regeneration. This keeps generation fast and gives the user control.

## Design Token Integration

The tool syncs with Figma to maintain visual consistency:

```
Figma File --> sync_figma_styles.py --> default.yaml --> System Prompt --> LLM Output
```

**Current tokens** (from UK National Figma guidelines):

| Token | Value | Usage |
|-------|-------|-------|
| Primary | `#25374B` (Cloudburst) | All text, strokes, labels, outlines |
| Blue | `#0875BE` | Highlighted/emphasised elements: marked points, key measurements |
| Teal | `#ACE3D9` | Filled/shaded regions: shape fills, bar fills, pie slices |
| Gray | `#5E6D7F` | Secondary descriptive text (axis titles, captions) |
| Grid | `#E5E6E8` | Grid lines |
| White | `#FFFFFF` | Background and unshaded areas |
| Font | Proxima Nova | All text (words and numbers) |
| Math Font | KaTeX_Main | Mathematical variables (italic) |
| Standard stroke | 3px | Shape outlines, axes, main lines |
| Labelling stroke | 2px | Dimension lines, annotations, dashed lines |

## Output Format

For each diagram, the tool produces:

### 1. SVG File (saved locally)
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 260">
  <title>Number line 0 to 10</title>
  <desc>A horizontal number line...</desc>
  <!-- diagram content -->
</svg>
```

### 2. Hosted PNG (HTTPS URL)
```
https://i.ibb.co/sv61FVtX/Number-line-0-10.jpg
```

### 3. DraftImage JSX (ready to paste)
```jsx
<DraftImage
  width={260}
  height={260}
  id="c871fc2c-dc22-414b-a15c-c60a7f30d727"
  url="https://i.ibb.co/sv61FVtX/Number-line-0-10.jpg"
  notesForImageCreator="A horizontal number line from 0 to 10 with filled green dots marking 3 and 7."
/>
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| LLM (SVG Generation) | Gemini 3.1 Pro via OpenRouter (thinking model, ~30-60s per generation) |
| Image Validation | Claude Sonnet 4.5 vision via OpenRouter |
| SVG Rendering | Playwright + persistent headless Chromium |
| Image Hosting | imgbb (primary), Imgur (fallback) |
| Web Framework | Flask (local), gunicorn (production/Docker) |
| Sharing | Render (permanent URL), ngrok (quick share), Docker |
| Config | YAML + python-dotenv |
| Design Sync | Figma REST API |

## API Keys Required

| Key | Source | Cost |
|-----|--------|------|
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai/) | ~$0.01-0.05 per diagram (includes validation) |
| `IMGBB_API_KEY` | [api.imgbb.com](https://api.imgbb.com/) | Free |
| `NGROK_AUTH_TOKEN` | [dashboard.ngrok.com](https://dashboard.ngrok.com/signup) | Free (optional, for quick sharing via `--share`) |
| `FIGMA_API_TOKEN` | [figma.com/developers](https://www.figma.com/developers/) | Free (optional, for style sync) |

## Performance

| Metric | Value |
|--------|-------|
| Single diagram (generate + validate + upload) | ~30-90 seconds |
| With manual retry | ~60-150 seconds |
| Chromium cold-start | ~3-5s first render only (persistent browser reused after) |
| Upload after validation | Near-instant (PNG reused, no re-render) |
| LLM tokens per diagram (no retries) | ~1,500 in / ~2,000 out |
| LLM tokens per diagram (with validation) | ~3,000-5,000 total |
| Cost per diagram | ~$0.02-0.10 (Gemini 3.1 Pro thinking tokens + Sonnet validation) |
| SVG file size | ~1-3 KB |
| PNG file size (2x) | ~5-15 KB |

## Deployment & Sharing

### Option 1: Render (current deployment)

Live at: **https://maths-svg-generator.onrender.com/**

Auto-deploys from the [maths-svg-generator](https://github.com/mmendozajara/maths-svg-generator) GitHub repo on push.

### Option 2: Docker (any host)

```bash
docker build -t maths-svg-generator .
docker run -p 8080:8080 -e OPENROUTER_API_KEY=... -e IMGBB_API_KEY=... maths-svg-generator
```

### Option 3: ngrok (quick share from local)

```bash
python app.py --share
```

Requires your machine to stay on. URL changes on restart.

### Option 4: Git Clone (local setup)

See `SETUP.md` for detailed coworker instructions.

## Future Enhancements

- [ ] Additional diagram types (Venn diagrams, tree diagrams, probability trees)
- [ ] Diagram editing/refinement ("make the line thicker", "change 3 to 5")
- [ ] Template library (save and reuse common diagram patterns)
- [ ] Direct Figma plugin integration (paste SVG into Figma frames)
- [ ] Usage dashboard (track generation counts, costs, common diagram types)

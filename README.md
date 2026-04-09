# Maths SVG Generator

Generate mathematical diagrams as SVG from natural language descriptions, with optional Figma design token styling.

## What It Does

Type a description like _"A number line from 0 to 10 with 3 and 7 marked"_ and get back:

1. A production-ready **SVG** — optionally matching your Figma colour palette and typography, or clean generic styling
2. A **PNG** uploaded to image hosting (imgbb) with live upload status indicators
3. A ready-to-paste **`<DraftImage>`** JSX snippet with the HTTPS URL
4. **Image validation** via vision LLM — checks cutoff, accuracy, and mathematical consistency (automatic or on-demand via Validate button)
5. **Manual retry** — if validation flags issues, user sees them and decides whether to retry
6. **Download SVG** — direct download link on every result card
7. **JSX file processing** — upload a JSX file with `image-coming-soon.svg` placeholders and get back the same file with generated `<DraftImage>` replacements

```jsx
<DraftImage
  width={260}
  height={260}
  id="c871fc2c-dc22-414b-a15c-c60a7f30d727"
  url="https://i.ibb.co/sv61FVtX/Number-line-0-10.jpg"
  notesForImageCreator="A horizontal number line from 0 to 10 with filled green dots marking 3 and 7."
/>
```

## Supported Diagram Types

| Type | Examples |
|------|----------|
| **Number Lines** | Horizontal/vertical axes with marked points, intervals |
| **Coordinate Graphs** | Plotted functions (y = x^2), multiple series, legends |
| **Geometry** | Triangles, angles, right-angle markers, labelled vertices |
| **Bar Charts** | Vertical/horizontal bars with labels and values |
| **Pie Charts** | Sectors with percentages and leader lines |
| **Fractions** | Bar models, area models, shaded sectors |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Set up environment variables

Add these to the `.env` file in the project root:

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here
IMGBB_API_KEY=your-imgbb-key-here
NGROK_AUTH_TOKEN=your-ngrok-token-here    # optional, for --share
```

- **OpenRouter API key** — [openrouter.ai](https://openrouter.ai/) (for LLM calls)
- **imgbb API key** — [api.imgbb.com](https://api.imgbb.com/) (free image hosting)
- **ngrok auth token** — [dashboard.ngrok.com](https://dashboard.ngrok.com/signup) (free, for sharing)

### 3. Run

**Web interface (local):**
```bash
python app.py
# Opens at http://localhost:5000
```

**Web interface (share publicly):**
```bash
python app.py --share
# Prints a public https://xxxx.ngrok-free.app URL
```

**CLI — single diagram:**
```bash
python generate.py "A right triangle with sides 3, 4, 5" --upload
```

**CLI — batch from TXT:**
```bash
python generate.py --batch descriptions.txt --upload
```

**CLI — batch from JSON:**
```bash
python generate.py --batch requests.json --upload
```

**CLI — JSX file processing:**
```bash
python generate.py --jsx input.jsx --upload
python generate.py --jsx input.jsx --upload --output output_dir/
```

## Web Interface

The web UI at `http://localhost:5000` has three tabs:

### Single Tab
- Type a description, set dimensions, generate one diagram
- **Figma styling toggle** — check "Use Figma Styling" to apply brand colours/fonts, or leave unchecked for clean generic styling (default: off)
- Toggle upload on/off (off = `url="upload this image first"` placeholder)
- **Upload status indicator** — shows uploading/uploaded/error state on each result card
- **Validate button** — manually trigger vision validation on any result (useful when auto-validation is skipped)
- **Download SVG** — direct download link on every result card
- **Manual retry** — click the orange Retry button on cards with validation issues to regenerate with fix instructions (no auto-retry — user decides)

### Batch Tab
- **File upload** — drag-and-drop a `.txt` file (one description per line)
- **Manual entry** — type descriptions directly in a textarea
- **Progress bar** with live timer and item counter
- **Cancel button** — stop mid-batch (completes current item gracefully)
- **Retry indication** — shows when image validation triggered retries
- **Manual retry** — Retry button on individual batch result cards with issues
- **Batch downloads** — Download SVGs (.zip), Download Codes (.txt), or Copy All

### JSX Processor Tab
- **File upload** — drag-and-drop a `.jsx` file containing placeholder `<DraftImage>` or `<Image>` tags with `image-coming-soon.svg` paths
- **Placeholder preview** — shows all detected placeholders with editable descriptions, width/height overrides
- **Sequential generation** — generates SVGs for each placeholder using the `accessibilityDescription` as the prompt
- **Progress bar** with live timer and ETA
- **Cancel button** — stop mid-processing
- **Download Modified JSX** — outputs the original JSX with all placeholders replaced by generated `<DraftImage>` codes

Keyboard shortcut: `Ctrl+Enter` to generate.

## CLI Options

```
python generate.py [description] [options]

Arguments:
  description              Natural language description of the diagram

Options:
  --name NAME              Output filename (without .svg)
  --width WIDTH            SVG width in pixels (default: 260)
  --height HEIGHT          SVG height in pixels (default: 260)
  --upload                 Upload to image host, use HTTPS URL in DraftImage
  --batch FILE             Path to .txt or .json file for batch generation
  --jsx FILE               Path to a JSX file — finds placeholder images and generates replacements
  --output DIR             Output directory for modified JSX file (default: same as input)
  --config FILE            Path to custom YAML config
  --dry-run                Print SVG without saving
```

### Batch TXT format (one description per line)

```
A number line from -5 to 5
triangle | A right triangle with sides 3, 4, 5
A coordinate graph of y = x squared from -3 to 3
pie_chart | A pie chart showing 40% red, 35% blue, 25% green
```

Lines starting with `#` are ignored. Optional `name | description` format for custom filenames.

### Batch JSON format

```json
[
  {"id": "img001", "description": "A number line from -5 to 5"},
  {"id": "img002", "description": "A coordinate graph of y = 2x + 1", "width": 300, "height": 300}
]
```

### JSX file processing

The `--jsx` flag accepts a JSX file and scans for `<DraftImage>` or `<Image>` tags containing `image-coming-soon.svg` in their `path`, `url`, or `src` attribute. For each placeholder found, the tool:

1. Extracts the generation prompt from `accessibilityDescription`, `notesForImageCreator`, or `alt`
2. Extracts dimensions from `width`/`height` attributes (defaults to 260x260)
3. Generates an SVG for each placeholder
4. Replaces the placeholder tag with a new `<DraftImage>` containing the hosted URL (if `--upload`) or a placeholder URL
5. Writes the modified JSX to `{original_name}_with_images.jsx`

```bash
# Process a JSX file and upload generated images
python generate.py --jsx lesson_content.jsx --upload

# Output to a specific directory
python generate.py --jsx lesson_content.jsx --upload --output processed/
```

## Image Validation

Every generated diagram can be validated by a vision LLM that checks:

1. **Cutoff / Clipping** — no text, lines, or shapes cut off at image edges
2. **Mathematical Accuracy** — curve shapes, values, labels, and proportions match the description

Validation runs automatically when `image_validation_retries` > 0. When set to 0 (default), validation is skipped during generation but can be triggered manually via the **Validate** button on any result card.

If validation finds issues, the result is shown with the issues listed. The user can then click the **Retry** button to regenerate with fix instructions. There is no auto-retry — this keeps generation fast and gives the user control.

The validation status is shown:
- **Web UI** — green/red/yellow badge on each result card; orange Retry button on cards with issues; blue Validate button when validation was skipped
- **CLI** — `Validation: PASSED` or `Validation: ISSUES FOUND` with details

Configure in `default.yaml`:
```yaml
models:
  svg_generator: google/gemini-3.1-pro-preview-20260219
  image_validator: anthropic/claude-sonnet-4-5
llm:
  max_tokens: 32768
  image_validation_retries: 0    # 0 = validate once, no auto-retry
```

## Performance Optimisations

- **Thinking budget control** — Gemini 3.1 Pro's internal reasoning can be disabled (default), capped at a token budget, or left uncapped. Disabled is fastest (~30-40s) with minimal quality loss
- **Persistent Chromium browser** — a single headless Chromium instance is launched once and reused for all SVG-to-PNG renders, avoiding ~3-5s cold-start overhead per render
- **PNG reuse** — the PNG rendered during validation is passed directly to the upload step, eliminating a redundant re-render
- **Parallel upload** — SVG is returned to the frontend immediately; PNG upload to imgbb runs in a background thread. Frontend polls `/api/upload-status/<id>` for the hosted URL
- **Prompt caching** — system prompt uses `cache_control: {"type": "ephemeral"}` for OpenRouter caching (~75% savings on cached reads)
- **No auto-retry** — validation runs once and shows issues to the user instead of silently doubling generation time with auto-regeneration

## Figma Style Sync

Pull colours, fonts, and stroke widths from a Figma design file:

```bash
python sync_figma_styles.py --file-key YOUR_FIGMA_FILE_KEY
```

This updates `project-configs/default.yaml` so all generated SVGs match your design system. Requires `FIGMA_API_TOKEN` in `.env`.

## Project Structure

```
Image generator/
  app.py                   # Flask web server + REST API (incl. /api/validate endpoint)
  generate.py              # CLI entry point (single + batch + JSX processing)
  svg_generator.py         # LLM SVG generation + image validation loop
  validate_image.py        # Vision LLM image validation
  jsx_embed.py             # DraftImage JSX formatter + placeholder parser
  upload_imgur.py           # SVG -> PNG -> imgbb/Imgur upload (persistent browser)
  sync_figma_styles.py      # Figma REST API -> YAML style sync
  config.py                # YAML + env config loader (incl. style guide selection)
  llm_client.py            # Thread-safe OpenRouter API client (text + vision + thinking budget)
  Dockerfile               # Production container (Chromium + gunicorn)
  .env.example             # Template for required environment variables
  SETUP.md                 # Setup guide for coworkers
  project-configs/
    default.yaml            # Colours, fonts, model, dimensions, thinking budget
  prompts/
    svg_system.md           # LLM system prompt template ({{STYLING}} + {{STYLE_GUIDE}} placeholders)
    style_guide_figma.md    # Figma brand style guide (colours, fonts, strokes, examples)
    style_guide_generic.md  # Clean generic style guide (no hardcoded brand values)
    validate_image.md       # Vision validation prompt (cutoff + accuracy)
  templates/
    index.html              # Web UI (single + batch + JSX processor tabs)
  output/                   # Generated SVG files
  requirements.txt         # Python dependencies
```

## How It Works

```
Description --> LLM (Claude) --> SVG --> Validate XML
                                              |
                                        Retry if invalid
                                              |
                                  SVG --> PNG (persistent Chromium)
                                              |
                                       Vision LLM Validation
                                       (cutoff + accuracy +
                                        math consistency)
                                              |
                                   If issues: show to user
                                   with Retry button
                                              |
                                   PNG upload (background thread)
                                   --> imgbb --> HTTPS URL
                                              |
                                        <DraftImage> JSX snippet
```

1. **System prompt** is loaded from `prompts/svg_system.md` and populated with styling constants — either Figma brand tokens or generic clean defaults, based on the "Use Figma Styling" toggle (cached via `cache_control`)
2. **LLM** (Gemini 3.1 Pro via OpenRouter) generates the SVG + metadata. Thinking budget is configurable (disabled by default for speed)
3. **XML validation** checks the SVG is well-formed; retries on parse errors
4. **Chromium** (persistent headless instance via Playwright) renders the SVG to a crisp 2x PNG
5. **Vision validation** (Sonnet 4.5) checks for cutoff/clipping, mathematical accuracy, and mathematical consistency (e.g., Pythagoras check on right triangles). Can also be triggered manually via the Validate button
6. **Result shown** — SVG returned immediately to frontend with validation status, download link, and upload indicator. If issues found, user sees them + a Retry button
7. **Background upload** — PNG upload to imgbb runs in a daemon thread; frontend polls for the hosted URL with live status indicator
8. **DraftImage** JSX snippet is formatted with the URL and accessibility description

## Configuration

Edit `project-configs/default.yaml`:

```yaml
models:
  svg_generator: google/gemini-3.1-pro-preview-20260219  # Thinking model for SVG generation
  image_validator: anthropic/claude-sonnet-4-5            # Vision model for validation
llm:
  temperature: 0.2            # Lower = more consistent
  max_tokens: 32768           # Must be high — Gemini 3.1 Pro uses ~7000+ thinking tokens internally
  thinking_budget: 0          # 0 = disabled (fastest), positive int = cap, omit/null = uncapped
  image_validation_retries: 0 # 0 = validate once, no auto-retry (user clicks Retry if needed)
defaults:
  width: 260                  # Default SVG dimensions
  height: 260
styling:                       # Used when "Use Figma Styling" is checked (off by default)
  primary_color: '#25374B'    # Cloudburst — main text, strokes, labels
  secondary_color: '#0875BE'  # Blue — headings, highlights, accent lines
  fill_color: '#ACE3D9'       # Teal — shaded regions, filled areas
  label_color: '#5E6D7F'      # Gray — secondary/descriptive text
  grid_color: '#E5E6E8'       # Light gray — grid lines
  font_family: Proxima Nova, Arial, Helvetica, sans-serif
  math_font: KaTeX_Main
  font_size: 16
```

## Deployment & Sharing

### Option 1: Render (current deployment)

Live at: **https://maths-svg-generator.onrender.com/**

Auto-deploys from the [maths-svg-generator](https://github.com/mmendozajara/maths-svg-generator) GitHub repo on push.

### Option 2: ngrok (quick sharing)

Share your running local instance instantly:

```bash
python app.py --share
# Output:
#   Local:  http://localhost:5000
#   Public: https://xxxx.ngrok-free.app
```

Requires `NGROK_AUTH_TOKEN` in `.env` (free at [ngrok.com](https://dashboard.ngrok.com/signup)). URL changes on restart; requires your machine to stay on.

### Option 3: Docker (any host)

```bash
docker build -t maths-svg-generator .
docker run -p 8080:8080 \
  -e OPENROUTER_API_KEY=sk-or-v1-... \
  -e IMGBB_API_KEY=... \
  maths-svg-generator
```

### Option 4: Git Clone (local)

```bash
git clone <repo-url>
cd <repo-name>
pip install -r requirements.txt
python -m playwright install chromium
# Add API keys to .env
python app.py
```

See `SETUP.md` for detailed coworker setup instructions.

## Requirements

- Python 3.12+
- Playwright + Chromium (for SVG to PNG conversion)
- OpenRouter API key (LLM access)
- imgbb API key (free image hosting)

# Setup Guide — Maths SVG Image Generator

## Option A: Use the hosted version (easiest)

Just open the URL in your browser — no setup needed:

> **https://maths-svg-generator.onrender.com/**

---

## Option B: Render (current team deployment)

The app is deployed on Render and auto-deploys from GitHub on push:

> **https://maths-svg-generator.onrender.com/**

To update: push to the [maths-svg-generator](https://github.com/mmendozajara/maths-svg-generator) GitHub repo → Render auto-redeploys.

---

## Option C: Run with Docker

If you have Docker installed, you can run it without installing Python or Playwright:

```bash
cd "Image generator"
docker build -t maths-svg-generator .
docker run -p 8080:8080 \
  -e OPENROUTER_API_KEY=sk-or-v1-your-key-here \
  -e IMGBB_API_KEY=your-key-here \
  maths-svg-generator
```

Open **http://localhost:8080** in your browser.

---

## Option D: Run locally on your own machine

### Prerequisites

- **Python 3.12+** — [python.org/downloads](https://www.python.org/downloads/)
- **Git** — [git-scm.com](https://git-scm.com/)

### 1. Clone the repo

```bash
git clone <repo-url>
cd <repo-name>
```

### 2. Install Python packages

```bash
pip install -r requirements.txt
```

### 3. Install Chromium (used to convert SVGs to PNGs)

```bash
python -m playwright install chromium
```

### 4. Set up API keys

Copy the example env file:

```bash
cp .env.example .env
```

Then edit `.env` and fill in your keys:

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here
IMGBB_API_KEY=your-key-here
```

**Where to get the keys:**

| Key | Where | Cost |
|-----|-------|------|
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | Pay-per-use (~$0.01-0.05 per diagram) |
| `IMGBB_API_KEY` | [api.imgbb.com](https://api.imgbb.com/) | Free |

> **Note:** Ask Jara if you'd like to use the shared team keys instead of creating your own.

### 5. Run the tool

```bash
python app.py
```

Open **http://localhost:5000** in your browser. That's it!

---

## Quick Usage

1. Type a description like: `A number line from 0 to 10 with 3 and 7 marked`
2. Optionally check **Use Figma Styling** to apply brand colours/fonts (off by default for cleaner, faster output)
3. Click **Generate**
4. Copy the `<DraftImage>` code, click **Download SVG**, or wait for the upload to complete (status shown on the card)
5. Click the **Validate** button to run vision validation on any result
6. If there are validation issues, click the orange **Retry** button to regenerate with fixes

### Batch mode

- Switch to the **Batch** tab
- Upload a `.txt` file (one description per line) or type multiple descriptions
- Optionally check **Use Figma Styling**
- Click **Generate All**
- Download results as ZIP or copy all codes at once

### JSX Processor mode

- Switch to the **JSX Processor** tab
- Upload a `.jsx` file containing placeholder `<DraftImage>` or `<Image>` tags with `image-coming-soon.svg` paths
- Review the detected placeholders — edit descriptions or dimensions if needed
- Optionally check **Use Figma Styling**
- Click **Generate All** to process each placeholder sequentially
- Click **Download Modified JSX** to get the file with all placeholders replaced

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `playwright` not found | Run `python -m playwright install chromium` |
| API key error | Check that `.env` is in the project root |
| Port 5000 in use | Run `python app.py --port 5001` to use a different port |
| SVGs look wrong | Try a more specific description — include colours, labels, and positions |
| Generation takes 30-90s | This is normal — Gemini 3.1 Pro is a thinking model. With thinking disabled (default), generation is ~30-40s. The persistent browser, prompt caching, and parallel upload optimisations are already applied |
| Validation issues shown | No auto-retry — click the orange Retry button if the diagram needs fixing |
| No Validate button | Validate button appears when auto-validation is skipped (the default). Click it to run vision validation on-demand |
| Upload status not showing | Check that the Upload checkbox is ticked. The upload indicator shows on each card while the background upload completes |

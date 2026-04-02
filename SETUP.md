# Setup Guide — Maths SVG Image Generator

## Option A: Use the hosted version (easiest)

Just open the URL in your browser — no setup needed:

> **Ask Jara for the current deployment URL**

---

## Option B: Deploy to Render (recommended for teams)

Render gives you a permanent URL that stays up 24/7 — no need to keep your laptop running.

### One-time setup (admin only)

1. Go to [render.com](https://render.com/) and sign in with GitHub
2. Click **New** → **Web Service** → connect the `maths-svg-generator` repo
3. Render auto-detects the Dockerfile — accept the defaults
4. Choose the **Starter** plan ($7/month) — needed for Playwright/Chromium memory
5. Add environment variables in the Render dashboard:
   ```
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   IMGBB_API_KEY=your-key-here
   ```
6. Click **Deploy**. You'll get a permanent URL like `https://maths-svg-generator.onrender.com`

**Cost:** ~$7/month on the Starter plan.

### Updating

Push to GitHub → Render auto-redeploys. That's it.

---

## Option C: Deploy to Railway (alternative)

1. Go to [railway.app](https://railway.app/) and sign in with GitHub
2. Click **New Project** → **Deploy from GitHub repo**
3. Add environment variables: `OPENROUTER_API_KEY`, `IMGBB_API_KEY`
4. Railway auto-detects the Dockerfile and deploys

**Cost:** ~$5/month on the Hobby plan.

---

## Option D: Run with Docker

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

## Option E: Run locally on your own machine

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
2. Click **Generate**
3. Copy the `<DraftImage>` code or download the SVG
4. If there are validation issues, click the orange **Retry** button to regenerate with fixes

### Batch mode

- Switch to the **Batch** tab
- Upload a `.txt` file (one description per line) or type multiple descriptions
- Click **Generate All**
- Download results as ZIP or copy all codes at once

### JSX Processor mode

- Switch to the **JSX Processor** tab
- Upload a `.jsx` file containing placeholder `<DraftImage>` or `<Image>` tags with `image-coming-soon.svg` paths
- Review the detected placeholders — edit descriptions or dimensions if needed
- Click **Generate All** to process each placeholder sequentially
- Click **Download Modified JSX** to get the file with all placeholders replaced

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `playwright` not found | Run `python -m playwright install chromium` |
| API key error | Check that `.env` is in the project root |
| Port 5000 in use | Run `python app.py --port 5001` to use a different port |
| SVGs look wrong | Try a more specific description — include colours, labels, and positions |
| Render deploy fails | Use the Starter plan ($7/month) — the free tier doesn't have enough memory for Playwright/Chromium |
| Validation too slow | This is normal — each retry cycle involves LLM generation + PNG render + vision check. The persistent browser and PNG reuse optimisations are already applied |

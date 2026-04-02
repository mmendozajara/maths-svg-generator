FROM python:3.12-slim

# Install system deps needed by Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Install Playwright Chromium
RUN python -m playwright install chromium

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p output

# Default port (Render/Railway inject PORT env var at runtime)
ENV PORT=8080
EXPOSE 8080

# Run with gunicorn for production (shell form so $PORT is expanded)
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 2 app:app

"""Thread-safe OpenRouter LLM client with retry logic."""

import json
import threading
import time

import requests


class LLMClient:
    """Synchronous OpenRouter client with usage tracking and retries."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, max_retries: int = 2):
        self.api_key = api_key
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0

    def call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Make an LLM call with retry logic. Returns the response text."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        system_message = {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
        payload = {
            "model": model,
            "messages": [
                system_message,
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.API_URL,
                    headers=headers,
                    json=payload,
                    timeout=300,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    with self._lock:
                        self.total_input_tokens += usage.get("prompt_tokens", 0)
                        self.total_output_tokens += usage.get("completion_tokens", 0)
                        self.total_calls += 1
                    return text
                elif resp.status_code >= 500:
                    last_error = f"Server error {resp.status_code}: {resp.text[:200]}"
                elif resp.status_code == 429:
                    last_error = "Rate limited"
                else:
                    raise RuntimeError(
                        f"LLM call failed ({resp.status_code}): {resp.text[:500]}"
                    )
            except requests.exceptions.Timeout:
                last_error = "Request timed out"
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"

            if attempt < self.max_retries:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)

        raise RuntimeError(f"LLM call failed after {self.max_retries + 1} attempts: {last_error}")

    def call_vision(
        self,
        model: str,
        system_prompt: str,
        user_text: str,
        image_base64: str,
        image_media_type: str = "image/png",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Make a vision LLM call with an image. Returns the response text."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        system_message = {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
        payload = {
            "model": model,
            "messages": [
                system_message,
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_media_type};base64,{image_base64}",
                            },
                        },
                    ],
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.API_URL,
                    headers=headers,
                    json=payload,
                    timeout=300,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    with self._lock:
                        self.total_input_tokens += usage.get("prompt_tokens", 0)
                        self.total_output_tokens += usage.get("completion_tokens", 0)
                        self.total_calls += 1
                    return text
                elif resp.status_code >= 500:
                    last_error = f"Server error {resp.status_code}: {resp.text[:200]}"
                elif resp.status_code == 429:
                    last_error = "Rate limited"
                else:
                    raise RuntimeError(
                        f"Vision LLM call failed ({resp.status_code}): {resp.text[:500]}"
                    )
            except requests.exceptions.Timeout:
                last_error = "Request timed out"
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"

            if attempt < self.max_retries:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)

        raise RuntimeError(f"Vision LLM call failed after {self.max_retries + 1} attempts: {last_error}")

    def get_usage_summary(self) -> dict:
        """Return cumulative usage stats."""
        with self._lock:
            return {
                "total_calls": self.total_calls,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_input_tokens + self.total_output_tokens,
            }


def parse_json_response(text: str) -> dict | list:
    """Parse JSON from an LLM response, handling markdown code fences."""
    cleaned = text.strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line (```)
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object or array
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = cleaned.find(start_char)
        end = cleaned.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not parse JSON from LLM response:\n{text[:500]}")

"""Configuration loader for Maths SVG Image Generator."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ImageGenConfig:
    """Configuration loaded from YAML."""

    def __init__(self, config_path: str = None):
        self.base_dir = Path(__file__).parent

        # Load .env (check project root first, then parent for shared setups)
        load_dotenv(self.base_dir / ".env")
        load_dotenv(self.base_dir.parent / ".env")

        if config_path is None:
            config_path = self.base_dir / "project-configs" / "default.yaml"
        self.config_path = Path(config_path)

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        # Project
        self.name = raw["project"]["name"]

        # Models
        self.model = raw["models"]["svg_generator"]
        self.image_validator_model = raw["models"].get("image_validator", self.model)

        # LLM settings
        llm = raw.get("llm", {})
        self.temperature = llm.get("temperature", 0.2)
        self.max_tokens = llm.get("max_tokens", 8192)
        self.max_retries = llm.get("max_retries", 2)
        self.validation_retries = llm.get("validation_retries", 1)
        self.image_validation_retries = llm.get("image_validation_retries", 3)

        # Validation prompt path
        self.validation_prompt_path = self.base_dir / "prompts" / "validate_image.md"

        # Default dimensions
        defaults = raw.get("defaults", {})
        self.default_width = defaults.get("width", 260)
        self.default_height = defaults.get("height", 260)

        # Styling
        self.styling = raw.get("styling", {})

        # Prompt path
        self.prompt_path = self.base_dir / "prompts" / "svg_system.md"

        # Output
        self.output_dir = self.base_dir / "output"

        # API keys
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.imgur_client_id = os.environ.get("IMGUR_CLIENT_ID", "")
        self.imgbb_api_key = os.environ.get("IMGBB_API_KEY", "")

    @property
    def has_upload_key(self) -> bool:
        """Check if any image hosting API key is configured."""
        return bool(self.imgbb_api_key or self.imgur_client_id)

    def ensure_output_dir(self):
        """Create output directory if it doesn't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_styling_block(self) -> str:
        """Format styling config as text for the system prompt."""
        lines = []
        for key, value in self.styling.items():
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {value}")
        return "\n".join(lines)

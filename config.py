"""Configuration management for WAHA FastAPI service."""
import os
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=value file (like .env). Returns dict of key -> value (stripped, quotes removed)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


class Settings(BaseSettings):
    """Application settings loaded from environment variables and optional auth file."""

    waha_base_url: str = "http://localhost:3000"
    waha_session: str = "default"
    waha_api_key: Optional[str] = None  # From WAHA_API_KEY env, .env, or waha_auth_file
    waha_auth_type: Literal["X-Api-Key", "Bearer", "none"] = "X-Api-Key"
    waha_auth_file: str = "waha-auth.env"  # File to load waha_api_key and waha_auth_type from
    waha_debug: bool = False  # Enable debug logging
    recipients_file: str = "recipients.txt"  # Path to recipients file (env: WAHA_RECIPIENTS_FILE)

    # Kafka (configurable via KAFKA_* env vars)
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_notification_payload: str = "notification-payload"
    kafka_consumer_group: str = "finvarta-whatsapp-notification-consumer"

    @model_validator(mode="before")
    @classmethod
    def _kafka_env_override(cls, data: Any) -> Any:
        """Support KAFKA_* env vars (overrides WAHA_-prefixed or defaults)."""
        if not isinstance(data, dict):
            return data
        for env_key, attr in [
            ("KAFKA_BOOTSTRAP_SERVERS", "kafka_bootstrap_servers"),
            ("KAFKA_TOPIC_NOTIFICATION_PAYLOAD", "kafka_topic_notification_payload"),
            ("KAFKA_CONSUMER_GROUP", "kafka_consumer_group"),
        ]:
            if env_key in os.environ:
                data[attr] = os.environ[env_key]
        return data

    @model_validator(mode="after")
    def _load_auth_from_file(self) -> "Settings":
        """Load waha_api_key and waha_auth_type from file when not set by env. Env overrides file."""
        path = Path(self.waha_auth_file)
        if not path.is_absolute():
            path = Path(__file__).parent / self.waha_auth_file
        parsed = _parse_env_file(path)
        if not parsed:
            return self
        # Env takes precedence: only use file when the env var is not set
        if "WAHA_API_KEY" in parsed and "WAHA_API_KEY" not in os.environ and parsed["WAHA_API_KEY"]:
            self.waha_api_key = parsed["WAHA_API_KEY"].strip()
        auth_map = {"x-api-key": "X-Api-Key", "bearer": "Bearer", "none": "none"}
        if "WAHA_AUTH_TYPE" in parsed and "WAHA_AUTH_TYPE" not in os.environ:
            v = parsed["WAHA_AUTH_TYPE"].strip().lower()
            if v in auth_map:
                self.waha_auth_type = auth_map[v]
        return self

    def model_post_init(self, __context):
        """Clean up API key after loading."""
        if self.waha_api_key:
            self.waha_api_key = self.waha_api_key.strip()
            # If key is empty after stripping, set to None
            if not self.waha_api_key:
                self.waha_api_key = None

    class Config:
        env_prefix = "WAHA_"
        case_sensitive = False
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()

# Debug: Check if .env or waha-auth.env exists and has WAHA_API_KEY but it's not loaded
_env_file_path = Path(__file__).parent / ".env"
_auth_file_path = Path(settings.waha_auth_file) if Path(settings.waha_auth_file).is_absolute() else Path(__file__).parent / settings.waha_auth_file
if not settings.waha_api_key:
    for _path, _name in [(_env_file_path, ".env"), (_auth_file_path, settings.waha_auth_file)]:
        if _path.exists():
            _content = _path.read_text(encoding="utf-8")
            _has = any("WAHA_API_KEY" in line and "=" in line for line in _content.split("\n"))
            if _has:
                import warnings
                warnings.warn(
                    f"{_name} at {_path} contains WAHA_API_KEY but it's not being loaded. "
                    "Check: 1) Empty value after =, 2) Extra spaces, 3) Quotes"
                )
                break

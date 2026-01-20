"""Load and parse mobile numbers from the recipients file."""
import re
from pathlib import Path
from typing import List

from config import settings


def number_to_chat_id(number: str) -> str | None:
    """Convert a phone number string to WhatsApp chat_id (e.g. +919920906247 -> 919920906247@c.us)."""
    digits = re.sub(r"\D", "", number)
    return f"{digits}@c.us" if len(digits) >= 10 else None


def load_recipients(filepath: Path) -> List[str]:
    """
    Load and parse chat IDs from the recipients file.

    - Reads the file (returns [] if missing).
    - Ignores empty lines and lines starting with #.
    - Extracts digits from each line; if len >= 10, formats as {digits}@c.us.
    - De-duplicates while preserving order.

    Returns:
        List of chat_id strings (e.g. ["919920906247@c.us", ...]).
    """
    if not filepath.exists():
        return []

    text = filepath.read_text(encoding="utf-8")
    seen: set[str] = set()
    result: List[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digits = re.sub(r"\D", "", line)
        if len(digits) < 10:
            continue
        chat_id = f"{digits}@c.us"
        if chat_id not in seen:
            seen.add(chat_id)
            result.append(chat_id)

    return result


def get_recipients_file_path() -> Path:
    """
    Resolve the recipients file path from settings.

    If the configured path is not absolute, it is resolved relative to the
    project root (directory containing config.py).
    """
    path = Path(settings.recipients_file)
    if not path.is_absolute():
        path = (Path(__file__).parent / path).resolve()
    return path

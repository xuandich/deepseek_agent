"""config.py — Central configuration for DeepSeek Agent."""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULTS = {
    # Browser
    "DEEPSEEK_URL": "https://chat.deepseek.com",
    "SESSION_DIR": str(Path.home() / ".deepseek-agent" / "session"),
    "HEADLESS": False,
    # Run the (non-headless) managed browser inside an Xvfb virtual display —
    # avoids headless-mode bot detection without popping up a real window.
    "VIRTUAL_DISPLAY": False,
    # Timing (milliseconds, kept to mirror the original Node config)
    "RESPONSE_TIMEOUT": 180_000,
    "STABLE_DELAY": 2_500,
    "SEND_DELAY": 400,
    # Agent
    "MAX_ITERATIONS": 60,
    "WORKING_DIR": str(Path.cwd()),
    # Output
    "MAX_OUTPUT_LENGTH": 8_000,
    "DEBUG": False,
}


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print(f"[deepseek-agent] Could not parse config file: {path}")
    return {}


class _Config:
    """Mutable config object — behaves like the original JS module.exports object."""

    def __init__(self) -> None:
        data = dict(_DEFAULTS)

        global_config_path = Path.home() / ".deepseek-agent" / "config.json"
        project_config_path = Path.cwd() / "deepseek-agent.config.json"

        data.update(_load_json(global_config_path))
        data.update(_load_json(project_config_path))
        data.pop("_comment", None)

        session_dir = Path(data["SESSION_DIR"])
        if not session_dir.is_absolute():
            session_dir = Path.cwd() / session_dir
        data["SESSION_DIR"] = str(session_dir)

        session_dir.mkdir(parents=True, exist_ok=True)
        (Path.home() / ".deepseek-agent" / "logs").mkdir(parents=True, exist_ok=True)

        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str):
        try:
            return self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value) -> None:
        self._data[name] = value


config = _Config()

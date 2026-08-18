"""Configuration loading with TOML + environment variable overrides.

Order of precedence (lowest → highest):
  1. built-in defaults
  2. project-level `.aide.toml` (if present)
  3. user-level `~/.config/aide/config.toml`
  4. environment variables AIDE_*
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aide.core.errors import ConfigError

APP_NAME = "aide"
CONFIG_DIR_NAME = "config"
ENV_PREFIX = "AIDE_"

DEFAULTS: dict[str, Any] = {
    "api": {
        "base_url": "http://localhost:11434/v1",
        "model": "gpt-oss:120b-cloud",
        "api_key": "ollama",
        "temperature": 0.7,
        "max_tokens": 4096,
        "timeout": 120.0,
        "provider": "openai_compat",
    },
    "models": {
        "openai_compat": {
            "default": "gpt-4o",
            "presets": {
                "gpt-4o": {"temperature": 0.7, "max_tokens": 4096},
                "gpt-4o-mini": {"temperature": 0.7, "max_tokens": 4096},
                "gpt-3.5-turbo": {"temperature": 0.7, "max_tokens": 4096},
            },
        },
        "anthropic": {
            "default": "claude-3-5-sonnet-20241022",
            "presets": {
                "claude-3-5-sonnet-20241022": {"temperature": 0.7, "max_tokens": 4096},
                "claude-3-5-haiku-20241022": {"temperature": 0.7, "max_tokens": 4096},
                "claude-3-opus-20240229": {"temperature": 0.7, "max_tokens": 4096},
            },
        },
        "ollama": {
            "default": "llama3.1",
            "presets": {
                "llama3.1": {"temperature": 0.7, "max_tokens": 4096},
                "llama3.1:8b": {"temperature": 0.7, "max_tokens": 4096},
                "codellama": {"temperature": 0.3, "max_tokens": 4096},
                "mistral": {"temperature": 0.7, "max_tokens": 4096},
            },
        },
    },
    "ui": {"theme": "gruvbox-dark"},
    "log": {"level": "INFO"},
}


@dataclass
class ApiConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float
    max_tokens: int
    timeout: float
    provider: str = "openai_compat"  # openai_compat, anthropic, ollama


@dataclass
class UiConfig:
    theme: str


@dataclass
class LogConfig:
    level: str


@dataclass
class Config:
    api: ApiConfig
    ui: UiConfig
    log: LogConfig
    path: Path | None = field(default=None)


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / APP_NAME


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / APP_NAME


def project_config_path(project_dir: Path | None = None) -> Path | None:
    """Project-local `.aide.toml`, if any, walking up from `project_dir`."""
    start = project_dir or Path.cwd()
    for directory in (start, *start.parents):
        candidate = directory / ".aide.toml"
        if candidate.is_file():
            return candidate
    return None


def _merge(deep: bool) -> dict[str, Any]:
    """Merge defaults then override from outermost to innermost file."""
    base = DEFAULTS
    result: dict[str, Any] = {}
    for key, value in _flatten(base):
        _set_path(result, key, value)
    for path in (project_config_path(), config_dir() / "config.toml"):
        if path and path.is_file():
            try:
                with path.open("rb") as fh:
                    data = tomllib.load(fh)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise ConfigError(f"Failed to read config {path}: {exc}") from exc
            for key, value in _flatten(data):
                _set_path(result, key, value)
    if deep:
        _apply_env(result)
    return result


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten(value, path))
        else:
            out.append((path, value))
    return out


def _set_path(target: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _apply_env(result: dict[str, Any]) -> None:
    for name, value in os.environ.items():
        if not name.startswith(ENV_PREFIX):
            continue
        key = name[len(ENV_PREFIX) :].lower().replace("__", ".")
        if not key or "." not in key:
            continue
        _set_path(result, key, value)


def load_config(project_dir: Path | None = None) -> Config:
    merged = _merge(deep=True)
    api = merged["api"]
    return Config(
        api=ApiConfig(
            base_url=str(api["base_url"]),
            model=str(api["model"]),
            api_key=str(api["api_key"]),
            temperature=float(api["temperature"]),
            max_tokens=int(api["max_tokens"]),
            timeout=float(api["timeout"]),
            provider=str(api.get("provider", "openai_compat")),
        ),
        ui=UiConfig(theme=str(merged["ui"]["theme"])),
        log=LogConfig(level=str(merged["log"]["level"].upper())),
        path=config_dir() / "config.toml",
    )


def scaffold_config(force: bool = False) -> Path:
    """Write `.aide.toml`-style user config if missing. Returns the path written."""
    path = config_dir() / "config.toml"
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "# aide configuration\n"
        "# See requirement.md Phase 1 for the full list of options.\n\n"
        "[api]\n"
        f'base_url = "{DEFAULTS["api"]["base_url"]}"\n'
        f'model = "{DEFAULTS["api"]["model"]}"\n'
        '# api_key = "ollama"   # env override: AIDE_API__API_KEY\n'
        f'provider = "{DEFAULTS["api"]["provider"]}"  # openai_compat, anthropic, ollama\n\n'
        "[models.openai_compat]\n"
        f'default = "{DEFAULTS["models"]["openai_compat"]["default"]}"\n'
        "[models.openai_compat.presets]\n"
        "gpt-4o = { temperature = 0.7, max_tokens = 4096 }\n"
        "gpt-4o-mini = { temperature = 0.7, max_tokens = 4096 }\n"
        "gpt-3.5-turbo = { temperature = 0.7, max_tokens = 4096 }\n\n"
        "[models.anthropic]\n"
        f'default = "{DEFAULTS["models"]["anthropic"]["default"]}"\n'
        "[models.anthropic.presets]\n"
        "claude-3-5-sonnet-20241022 = { temperature = 0.7, max_tokens = 4096 }\n"
        "claude-3-5-haiku-20241022 = { temperature = 0.7, max_tokens = 4096 }\n"
        "claude-3-opus-20240229 = { temperature = 0.7, max_tokens = 4096 }\n\n"
        "[models.ollama]\n"
        f'default = "{DEFAULTS["models"]["ollama"]["default"]}"\n'
        "[models.ollama.presets]\n"
        "llama3.1 = { temperature = 0.7, max_tokens = 4096 }\n"
        "llama3.1:8b = { temperature = 0.7, max_tokens = 4096 }\n"
        "codellama = { temperature = 0.3, max_tokens = 4096 }\n"
        "mistral = { temperature = 0.7, max_tokens = 4096 }\n\n"
        "[ui]\n"
        f'theme = "{DEFAULTS["ui"]["theme"]}"\n\n'
        "[log]\n"
        f'level = "{DEFAULTS["log"]["level"]}"\n'
    )
    path.write_text(body)
    return path


def get_model_presets(provider: str | None = None) -> dict[str, Any]:
    """Get model presets for a provider (or all providers if None)."""
    from aide.config import load_config

    config = load_config()
    models: dict[str, Any] = config.__dict__.get("_merged_models", DEFAULTS["models"])
    if provider:
        result: dict[str, Any] = models.get(provider, {})
        return result
    return models


def apply_model_preset(config: Config, model_name: str) -> Config:
    """Apply a model preset to the config."""
    provider = config.api.provider
    models = get_model_presets(provider)
    preset = models.get("presets", {}).get(model_name)
    if preset:
        config.api.model = model_name
        config.api.temperature = preset.get("temperature", config.api.temperature)
        config.api.max_tokens = preset.get("max_tokens", config.api.max_tokens)
    return config

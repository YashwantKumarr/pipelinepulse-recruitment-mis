"""Environment-based settings. Secrets are excluded from repr() and are never logged."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

VALID_PROVIDERS = frozenset({"rules", "ollama", "claude"})
VALID_ENVS = frozenset({"development", "test", "production"})


class ConfigError(ValueError):
    """Invalid configuration. Messages name the setting but never include its value."""


@dataclass(frozen=True)
class Settings:
    app_name: str = "TalentFlow AI"
    app_env: str = "development"
    database_url: str = "sqlite:///./talentflow.db"
    upload_dir: Path = Path("data/uploads")
    ai_provider: str = "rules"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    anthropic_api_key: str = field(default="", repr=False)
    anthropic_model: str = ""
    ai_timeout_seconds: float = 30.0
    max_resume_size_mb: int = 5
    enable_n8n_webhooks: bool = False
    n8n_shared_secret: str = field(default="", repr=False)
    feedback_sla_hours: int = 72

    @property
    def max_resume_bytes(self) -> int:
        return self.max_resume_size_mb * 1024 * 1024

    def validate(self) -> None:
        if not self.database_url:
            raise ConfigError("DATABASE_URL must not be empty.")
        if self.app_env not in VALID_ENVS:
            raise ConfigError("APP_ENV must be development, test or production.")
        if self.ai_provider not in VALID_PROVIDERS:
            raise ConfigError("AI_PROVIDER must be one of: claude, ollama, rules.")
        if self.ai_provider == "claude":
            if not self.anthropic_api_key:
                raise ConfigError("ANTHROPIC_API_KEY is required when AI_PROVIDER=claude.")
            if not self.anthropic_model:
                raise ConfigError("ANTHROPIC_MODEL is required when AI_PROVIDER=claude.")
        if self.ai_provider == "ollama" and not self.ollama_model:
            raise ConfigError("OLLAMA_MODEL is required when AI_PROVIDER=ollama.")
        if not 1 <= self.ai_timeout_seconds <= 300:
            raise ConfigError("AI_TIMEOUT_SECONDS must be between 1 and 300.")
        if not 1 <= self.max_resume_size_mb <= 25:
            raise ConfigError("MAX_RESUME_SIZE_MB must be between 1 and 25.")
        if not 1 <= self.feedback_sla_hours <= 24 * 30:
            raise ConfigError("FEEDBACK_SLA_HOURS must be between 1 and 720.")
        if self.enable_n8n_webhooks and len(self.n8n_shared_secret) < 16:
            raise ConfigError(
                "N8N_SHARED_SECRET must be at least 16 characters when ENABLE_N8N_WEBHOOKS=true."
            )


def _text(env: Mapping[str, str], key: str, default: str) -> str:
    raw = env.get(key)
    return default if raw is None else raw.strip()


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"", "0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} must be true or false.")


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{key} must be a whole number.") from exc


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number.") from exc


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        from dotenv import load_dotenv

        load_dotenv(override=False)
        env = os.environ
    d = Settings()
    settings = Settings(
        app_name=_text(env, "APP_NAME", d.app_name),
        app_env=_text(env, "APP_ENV", d.app_env),
        database_url=_text(env, "DATABASE_URL", d.database_url),
        upload_dir=Path(_text(env, "UPLOAD_DIR", str(d.upload_dir))),
        ai_provider=_text(env, "AI_PROVIDER", d.ai_provider).lower(),
        ollama_base_url=_text(env, "OLLAMA_BASE_URL", d.ollama_base_url),
        ollama_model=_text(env, "OLLAMA_MODEL", d.ollama_model),
        anthropic_api_key=_text(env, "ANTHROPIC_API_KEY", d.anthropic_api_key),
        anthropic_model=_text(env, "ANTHROPIC_MODEL", d.anthropic_model),
        ai_timeout_seconds=_float(env, "AI_TIMEOUT_SECONDS", d.ai_timeout_seconds),
        max_resume_size_mb=_int(env, "MAX_RESUME_SIZE_MB", d.max_resume_size_mb),
        enable_n8n_webhooks=_bool(env, "ENABLE_N8N_WEBHOOKS", d.enable_n8n_webhooks),
        n8n_shared_secret=_text(env, "N8N_SHARED_SECRET", d.n8n_shared_secret),
        feedback_sla_hours=_int(env, "FEEDBACK_SLA_HOURS", d.feedback_sla_hours),
    )
    settings.validate()
    return settings

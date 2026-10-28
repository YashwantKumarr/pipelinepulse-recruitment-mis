import pytest

from app.config import ConfigError, Settings, load_settings


def test_defaults_are_local_first_and_rules_only():
    settings = load_settings({})
    assert settings.ai_provider == "rules"
    assert settings.enable_n8n_webhooks is False
    assert settings.max_resume_size_mb == 5
    assert settings.feedback_sla_hours == 72


def test_claude_requires_api_key_and_model():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_settings({"AI_PROVIDER": "claude", "ANTHROPIC_MODEL": "some-model"})
    with pytest.raises(ConfigError, match="ANTHROPIC_MODEL"):
        load_settings({"AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-test-key-value"})


def test_config_error_never_echoes_secret_value():
    secret = "sk-ant-should-not-appear-123"
    with pytest.raises(ConfigError) as info:
        load_settings({"AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": secret, "ANTHROPIC_MODEL": ""})
    assert secret not in str(info.value)


def test_claude_configuration_is_accepted_when_complete():
    settings = load_settings(
        {"AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-test-key-value", "ANTHROPIC_MODEL": "model-x"}
    )
    assert settings.ai_provider == "claude"


def test_secrets_are_hidden_from_repr():
    settings = Settings(anthropic_api_key="sk-hidden-value-xyz", n8n_shared_secret="another-hidden-secret")
    assert "sk-hidden-value-xyz" not in repr(settings)
    assert "another-hidden-secret" not in repr(settings)


def test_webhooks_require_strong_secret():
    with pytest.raises(ConfigError, match="N8N_SHARED_SECRET"):
        load_settings({"ENABLE_N8N_WEBHOOKS": "true", "N8N_SHARED_SECRET": "short"})


@pytest.mark.parametrize(
    "env",
    [
        {"AI_PROVIDER": "gpt-magic"},
        {"APP_ENV": "staging"},
        {"MAX_RESUME_SIZE_MB": "0"},
        {"MAX_RESUME_SIZE_MB": "many"},
        {"MAX_RESUME_SIZE_MB": "100"},
        {"ENABLE_N8N_WEBHOOKS": "maybe"},
        {"FEEDBACK_SLA_HOURS": "0"},
        {"AI_TIMEOUT_SECONDS": "abc"},
        {"DATABASE_URL": "   "},
    ],
)
def test_invalid_configuration_is_rejected(env):
    with pytest.raises(ConfigError):
        load_settings(env)


def test_boolean_and_numeric_parsing():
    settings = load_settings(
        {"ENABLE_N8N_WEBHOOKS": "false", "MAX_RESUME_SIZE_MB": " 2 ", "FEEDBACK_SLA_HOURS": "48"}
    )
    assert settings.enable_n8n_webhooks is False
    assert settings.max_resume_size_mb == 2
    assert settings.feedback_sla_hours == 48
    assert settings.max_resume_bytes == 2 * 1024 * 1024

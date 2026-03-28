import pytest
from pydantic import ValidationError

from capy_discord.config import Settings


def test_backend_api_base_url_uses_dev_url():
    settings = Settings(
        backend_environment="dev",
        backend_api_dev_base_url="http://localhost:8080",
        backend_api_prod_base_url="https://api.example.com",
    )

    assert settings.backend_api_base_url == "http://localhost:8080"


def test_backend_api_base_url_uses_prod_url():
    settings = Settings(
        backend_environment="prod",
        backend_api_dev_base_url="http://localhost:8080",
        backend_api_prod_base_url="https://api.example.com",
    )

    assert settings.backend_api_base_url == "https://api.example.com"


def test_backend_api_base_url_requires_prod_url_when_prod_environment():
    settings = Settings(
        backend_environment="prod",
        backend_api_dev_base_url="http://localhost:8080",
        backend_api_prod_base_url="",
    )

    with pytest.raises(ValueError, match="backend_api_prod_base_url"):
        _ = settings.backend_api_base_url


def test_backend_environment_rejects_unknown_value():
    with pytest.raises(ValidationError):
        Settings.model_validate({"backend_environment": "staging"})

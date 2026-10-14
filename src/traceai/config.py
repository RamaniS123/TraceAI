"""Environment-based configuration; never render secret settings in responses."""
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEAI_", env_file=".env", extra="ignore")

    database_url: SecretStr
    api_token: SecretStr | None = None
    reset_token: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: SecretStr) -> SecretStr:
        try:
            valid = make_url(value.get_secret_value()).drivername == "postgresql+psycopg"
        except Exception:
            valid = False
        if not valid:
            raise ValueError("A postgresql+psycopg database URL is required")
        return value

"""Environment-based configuration; never render secret settings in responses."""
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEAI_", env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr
    api_token: SecretStr | None = None
    reset_token: SecretStr | None = None
    test_reset_enabled: bool = False
    storage_timeout_ms: int = Field(default=5000, ge=100, le=60000)

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername in ("postgres", "postgresql", "postgresql+psycopg")
        except Exception:
            valid = False
        if not valid:
            raise ValueError("A postgresql+psycopg database URL is required")
        return SecretStr(url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False))

    @model_validator(mode="after")
    def distinct_tokens(self):
        if self.api_token is not None and not self.api_token.get_secret_value():
            raise ValueError("API token must not be empty")
        if self.reset_token is not None and not self.reset_token.get_secret_value():
            raise ValueError("Reset token must not be empty")
        if self.api_token is not None and self.reset_token is not None and self.api_token == self.reset_token:
            raise ValueError("API and reset tokens must be distinct")
        return self

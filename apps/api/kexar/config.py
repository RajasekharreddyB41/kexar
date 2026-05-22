"""
Typed configuration loaded from environment variables.

Every env var the app needs is declared here with a type. Missing or
malformed values raise at startup, not at request time. Nothing else
in the codebase should call os.getenv directly. Import `settings` from
this module instead.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the Kexar backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # TrueFoundry AI Gateway
    # SecretStr keeps the key out of logs and tracebacks. Pydantic redacts
    # it on repr. Call .get_secret_value() only at the HTTP call site.
    truefoundry_api_key: SecretStr = Field(alias="TRUEFOUNDRY_API_KEY")
    truefoundry_base_url: str = Field(alias="TRUEFOUNDRY_BASE_URL")

    # Model identifiers. Three are simulated for the hackathon (we have
    # no card on file for OpenAI/Anthropic/Gemini through TrueFoundry).
    # The runtime treats requests to these as upstream failures so the
    # cascade demo stays real. Groq is the actual backstop.
    truefoundry_model_claude: str = Field(alias="TRUEFOUNDRY_MODEL_CLAUDE")
    truefoundry_model_gpt4o: str = Field(alias="TRUEFOUNDRY_MODEL_GPT4O")
    truefoundry_model_gemini: str = Field(alias="TRUEFOUNDRY_MODEL_GEMINI")
    truefoundry_model_groq: str = Field(alias="TRUEFOUNDRY_MODEL_GROQ")

    # Supabase Postgres. Optional during early dev so the test script
    # can run before we provision the database.
    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    # Server
    port: int = Field(default=8000, alias="PORT")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )
    env: Literal["development", "production"] = Field(
        default="development", alias="ENV"
    )

    # Per-run hard caps. Architecture doc, section "Budget and step caps".
    kexar_max_steps: int = Field(default=10, alias="KEXAR_MAX_STEPS")
    kexar_max_tokens: int = Field(default=20_000, alias="KEXAR_MAX_TOKENS")
    kexar_max_cost_usd: float = Field(default=0.50, alias="KEXAR_MAX_COST_USD")

    # CORS
    cors_allowed_origins: str = Field(
        default="http://localhost:3000", alias="CORS_ALLOWED_ORIGINS"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Split the comma-separated CORS string into a list."""
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.env == "development"

    def is_simulated_model(self, model: str) -> bool:
        """Whether this model identifier is one of our staged-failure stubs.

        Used by the runtime to fake upstream failures for the demo cascade
        when we do not have real provider credentials wired up.
        """
        return model.startswith("simulated-")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Reads .env once per process."""
    return Settings()


# Module-level singleton. Import this in other files:
#     from kexar.config import settings
settings = get_settings()

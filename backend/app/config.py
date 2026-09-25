"""Configuración central del backend data-mind (variables de entorno)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    MONGO_URI: str = "mongodb://127.0.0.1:27017/gueo2021"
    MONGO_DB: str = "gueo2021"

    # Proveedor LLM (OpenAI-compatible). Por defecto: OpenCode Go.
    # Primario: DeepSeek V4 Flash (rápido, barato, chat/completions verificado E2E).
    # Fallback: Muse Spark 1.3 Contributor (razonador, 1M contexto; ver nota Jev/F2a).
    # Lista viva: https://opencode.ai/zen/go/v1/models
    LLM_BASE_URL: str = "https://opencode.ai/zen/go/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-v4-flash"

    API_PORT: int = 8001
    LOG_LEVEL: str = "info"

    # Guardrails de solo lectura
    QUERY_TIMEOUT_MS: int = 15000
    DEFAULT_LIMIT: int = 50
    MAX_LIMIT: int = 500

    # Perf / timeouts (optimización velocidad sin romper API)
    LLM_TIMEOUT_S: float = 45.0  # OpenAI client+request timeout (rango 30-60s)
    ASK_DEADLINE_S: float = 90.0  # deadline global /ask (cierra stream con error si excede)
    DISTINCT_CACHE_TTL_S: int = 300  # 5min cache en memoria para distinct_values

    # F1/F2a: seam determinista + Jev (TypeSafe)
    JEV_ENABLED: bool = False
    JEV_API_KEY: str = ""
    JEV_MODEL: str = "jev-latest"
    ROUTER_MIN_CONF: float = 0.6
    VERIFY_CIFRAS_MIN: float = 0.7
    VERIFY_PII_MIN: float = 0.7
    VERIFY_CALIDAD_MIN: float = 1.0
    LLM_FALLBACK_MODEL: str = "muse-spark-1.3-contributor"


settings = Settings()

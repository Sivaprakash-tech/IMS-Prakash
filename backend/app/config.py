from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = Field(default="INFO")

    postgres_user: str = Field(default="ims")
    postgres_password: str = Field(default="ims_pw")
    postgres_db: str = Field(default="ims")
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)

    mongo_user: str = Field(default="ims")
    mongo_password: str = Field(default="ims_pw")
    mongo_host: str = Field(default="mongo")
    mongo_port: int = Field(default=27017)
    mongo_db: str = Field(default="ims_signals")

    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)

    queue_maxsize: int = Field(default=50_000)
    queue_backpressure_threshold: float = Field(default=0.80)
    dedup_window_seconds: int = Field(default=10)
    worker_count: int = Field(default=8)
    rate_limit_per_second: int = Field(default=1000)
    throughput_log_interval: int = Field(default=5)

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def mongo_uri(self) -> str:
        return (
            f"mongodb://{self.mongo_user}:{self.mongo_password}"
            f"@{self.mongo_host}:{self.mongo_port}/?authSource=admin"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

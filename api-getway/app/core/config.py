from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  AUTH_SERVICE_URL: str
  AI_NEWS_SERVICE_URL: str
  JWT_SECRET_KEY: str
  INTERNAL_SERVICE_SECRET: str
  JWT_ALGORITHM: str = "HS256"

  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
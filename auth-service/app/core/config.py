from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
  APP_NAME: str = "auth-service"
  
  DATABASE_URL: str
  DEBUG: bool = False

  JWT_SECRET: str
  JWT_ALGORITHM: str = "HS256"

  ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
  REFRESH_TOKEN_EXPIRE_DAYS: int = 7

  RESEND_COOL_DOWN_SECONDS: int = 60

  # For sending emails to users
  SENDER_EMAIL: str
  SENDER_PASSWORD: str

  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
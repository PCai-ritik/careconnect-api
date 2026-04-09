from pydantic_settings import BaseSettings, SettingsConfigDict
import os

dot_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")


class Settings(BaseSettings):
    # Assigning a default value (like an empty string) keeps Neovim's LSP quiet.
    # Pydantic will still overwrite this with the value from your .env file.
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    DATABASE_URL: str = ""

    model_config = SettingsConfigDict(env_file=dot_env_path)


settings = Settings()

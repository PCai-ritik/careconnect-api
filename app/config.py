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

    # LiveKit
    LIVEKIT_URL: str = ""
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""

    # AI Pipeline
    DEEPGRAM_API_KEY: str = ""
    SARVAM_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # Azure Blob Storage (Commented out temporarily)
    AZURE_STORAGE_ACCOUNT_NAME: str = "your_account_name"
    AZURE_STORAGE_ACCOUNT_KEY: str = "your_account_key"
    AZURE_STORAGE_CONTAINER_NAME: str = "careconnect-recordings"

    # AWS S3 Storage (Active for beta deployment)
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET_NAME: str = "careconnect-recordings"

    # Database Connection Pool
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO_POOL: bool = False

    model_config = SettingsConfigDict(env_file=dot_env_path)


settings = Settings()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    MILVUS_HOST: str
    REDIS_URL: str
    DASHSCOPE_API_KEY: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    JWT_EXPIRE_MINUTES: int
    CORS_ORIGINS: list[str]
    UPLOAD_DIR: str = "uploads"

    class Config:
        env_file = ".env"


settings = Settings()

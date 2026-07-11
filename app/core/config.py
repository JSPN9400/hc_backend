from pydantic_settings import BaseSettings
from typing import List
import json

class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    SUPER_ADMIN_USERNAME: str = "jaisankar"
    SUPER_ADMIN_PASSWORD: str = "jai@2024"
    SUPER_ADMIN_EMAIL: str = "jaisankar@happycontractor.in"
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = '["http://localhost:5173"]'

    @property
    def cors_origins_list(self) -> List[str]:
        return json.loads(self.CORS_ORIGINS)

    class Config:
        env_file = ".env"

settings = Settings()

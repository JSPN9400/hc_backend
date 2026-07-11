from pydantic_settings import BaseSettings
from typing import List
import json

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:Balaji%40006%23@db.uqrvnadpkzxnggnhbyjt.supabase.co:5432/postgres"
    SECRET_KEY: str = "hc-secret-key-vishwanath-2024-xk92"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    SUPER_ADMIN_USERNAME: str = "jaisankar"
    SUPER_ADMIN_PASSWORD: str = "jai@2024"
    SUPER_ADMIN_EMAIL: str = "jaisankar@happycontractor.in"
    ENVIRONMENT: str = "production"
    CORS_ORIGINS: str = "*"

    @property
    def cors_origins_list(self) -> List[str]:
        val = self.CORS_ORIGINS.strip()
        if val == "*":
            return ["*"]
        if val.startswith("["):
            try:
                return json.loads(val)
            except Exception:
                pass
        return [v.strip() for v in val.split(",") if v.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

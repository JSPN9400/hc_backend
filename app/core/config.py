from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres.uqrvnadpkzxnggnhbyjt:jai94000Qv@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
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
        return ["*"]

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

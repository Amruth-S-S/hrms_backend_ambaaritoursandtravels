from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "hrms"

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720

    ADMIN_NAME: str = "Super Admin"
    ADMIN_EMAIL: str = "admin@ambaaritoursandtravels.com"
    ADMIN_PASSWORD: str = "Admin@123"

    TIMEZONE: str = "Asia/Kolkata"
    CORS_ORIGINS: str = "http://localhost:3000"
    # Any localhost / 127.0.0.1 port, so the dev frontend works when Next picks 3001, 3002, ...
    CORS_ORIGIN_REGEX: str = r"http://(localhost|127\.0\.0\.1)(:\d+)?"
    MAX_SELFIE_MB: int = 5
    REVERSE_GEOCODE: bool = True
    # Sessions with no activity for this long are closed automatically on next login
    SESSION_IDLE_MINUTES: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()

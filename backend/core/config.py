from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Sentinel AMIS-RU Decision Support Engine"
    VERSION: str = "1.0"
    API_V1_STR: str = "/api"
    
    # CORS Configuration
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://0.0.0.0:3000"]
    
    model_config = SettingsConfigDict(case_sensitive=True)

settings = Settings()

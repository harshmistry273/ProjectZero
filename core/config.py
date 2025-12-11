from pydantic_settings import BaseSettings, SettingsConfigDict

# Class to manage environment variables
class Settings(BaseSettings):
    ELEVENLABS_API_KEY: str
    ELEVENLABS_MODEL: str
    ELEVENLABS_LIST_VOICES_URL: str
    
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

settings = Settings()
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://hrparser:hrparser@localhost:5432/hrparser"
    secret_key: str = "change-me"
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_path: str = "./telegram_session"
    superjob_client_id: str = ""
    superjob_client_secret: str = ""
    superjob_login: str = ""
    superjob_password: str = ""
    linkedin_email: str = ""
    linkedin_password: str = ""
    hh_client_id: str = ""
    hh_client_secret: str = ""
    hh_access_token: str = ""
    hh_refresh_token: str = ""
    hh_user_agent: str = "HrParser/1.0"
    hh_request_delay_seconds: float = 1.0
    hh_max_searches_per_cycle: int = 10
    vision_api_host: str = "127.0.0.1"
    vision_api_port: int = 3030
    vision_api_token: str = ""
    vision_folder_id: str = ""
    vision_profile_id: str = ""
    superjob_captcha_wait_seconds: int = 180
    hh_vision_folder_id: str = ""
    hh_vision_profile_id: str = ""
    hh_scraper_captcha_wait_seconds: int = 180
    poll_interval_seconds: int = 60
    dedup_similarity_threshold: int = 85

    class Config:
        env_file = ".env"


settings = Settings()

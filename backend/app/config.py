from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """全局配置，可通过 .env 覆盖。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "course-agent"
    debug: bool = True

    # 开发默认使用本地 SQLite，后续可切换 MySQL
    database_url: str = "sqlite:///./course_agent.db"
    database_name: str = ""

    # JWT 认证（生产环境务必通过 .env 覆盖）
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # DeepSeek 大模型（OpenAI 兼容接口）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 学期第一周的周一日期（用于推算当前教学周）
    semester_start: str = "2026-09-07"

    @property
    def effective_database_url(self) -> str:
        if not self.database_name:
            return self.database_url
        return make_url(self.database_url).set(database=self.database_name).render_as_string(
            hide_password=False
        )


settings = Settings()

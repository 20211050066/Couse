from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """全局配置，可通过 .env 覆盖。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "course-agent"
    debug: bool = True

    # PostgreSQL + pgvector；Docker Compose 中由环境变量覆盖 host
    database_url: str = "postgresql+psycopg://course:123456@127.0.0.1:5432/course_agent"
    database_name: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_socket_timeout_seconds: float = 0.5

    # JWT 认证（生产环境务必通过 .env 覆盖）
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # DeepSeek 大模型（OpenAI 兼容接口）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 混合检索：Query Rewrite + 双路召回 + RRF + Rerank
    rag_top_k: int = 10
    rag_rrf_k: int = 60
    rag_query_variants: int = 2
    rag_recall_min: int = 20
    rag_max_chunks_per_doc: int = 2
    rag_source_char_limit: int = 500
    rag_query_cache_ttl_seconds: int = 600
    rag_result_cache_ttl_seconds: int = 60

    # pgvector HNSW：与混合搜索文档中的调优参数保持一致
    hnsw_m: int = 24
    hnsw_ef_construction: int = 200
    hnsw_ef_search: int = 100

    # 智谱 Rerank；未配置时保持 RRF 排序
    rerank_api_key: str = ""
    rerank_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    rerank_model: str = "rerank"
    rerank_min_score: float = 0.1
    rerank_timeout_seconds: float = 10.0

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

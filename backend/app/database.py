from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

_database_url = settings.effective_database_url
# PostgreSQL 连接池启用探活，并用回收周期避免服务端空闲断连
engine = create_engine(
    _database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def initialize_database() -> None:
    """创建 pgvector 扩展、业务表和 RAG 索引。"""
    if engine.dialect.name != "postgresql":
        raise RuntimeError("RAG 混合检索要求 PostgreSQL + pgvector")

    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.create_all(bind=engine)

    from app.rag.schema import ensure_rag_indexes

    ensure_rag_indexes(engine)


def get_db():
    """FastAPI 依赖：为每个请求提供一个数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

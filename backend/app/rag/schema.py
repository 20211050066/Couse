"""PostgreSQL RAG 索引：pgvector HNSW 与中文 tsvector GIN。"""
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings


def hnsw_index_sql() -> str:
    return f"""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = {settings.hnsw_m}, ef_construction = {settings.hnsw_ef_construction})
    """


def tsvector_index_sql() -> str:
    return """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_search_text_gin
        ON document_chunks
        USING gin (to_tsvector('simple', search_text))
    """


def ensure_rag_indexes(engine: Engine) -> None:
    """按文档参数创建 HNSW 与全文索引，重复启动时保持幂等。"""
    with engine.begin() as connection:
        connection.execute(text(hnsw_index_sql()))
        connection.execute(text(tsvector_index_sql()))

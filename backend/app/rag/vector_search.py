"""基于 pgvector HNSW 的用户隔离向量召回。"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.document import CourseDocument, DocumentChunk


def vector_recall(
    db: Session,
    user_id: int,
    query_vector: list[float],
    limit: int,
) -> list[dict]:
    if not query_vector or limit <= 0:
        return []

    # ef_search 是查询时参数；值来自受控整数配置，避免 SET 参数化限制。
    db.execute(text(f"SET LOCAL hnsw.ef_search = {int(settings.hnsw_ef_search)}"))
    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    rows = (
        db.query(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            CourseDocument.filename,
            DocumentChunk.content,
            distance,
        )
        .join(CourseDocument, DocumentChunk.document_id == CourseDocument.id)
        .filter(
            CourseDocument.user_id == user_id,
            CourseDocument.status == "ready",
            DocumentChunk.embedding.isnot(None),
        )
        .order_by(distance)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": int(chunk_id),
            "document_id": document_id,
            "chunk_index": chunk_index,
            "filename": filename,
            "content": content,
            "vector_score": 1.0 - float(cosine_distance),
        }
        for chunk_id, document_id, chunk_index, filename, content, cosine_distance in rows
    ]

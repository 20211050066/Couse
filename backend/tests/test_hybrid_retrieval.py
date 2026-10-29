import pytest
from pgvector.sqlalchemy import Vector

from app.config import settings
from app.models.document import DocumentChunk
from app.rag import cache
from app.rag import query_rewrite, reranker, retriever
from app.rag.fusion import finalize_results, reciprocal_rank_fusion
from app.rag.schema import hnsw_index_sql, tsvector_index_sql


def _candidate(
    chunk_id: int,
    document_id: int = 1,
    content: str | None = None,
    filename: str = "guide.md",
) -> dict:
    return {
        "id": chunk_id,
        "document_id": document_id,
        "chunk_index": chunk_id,
        "filename": filename,
        "content": content or f"内容 {chunk_id}",
    }


def test_rrf_uses_rank_not_raw_scores():
    first = _candidate(1)
    second = _candidate(2)
    third = _candidate(3)
    fused = reciprocal_rank_fusion(
        [
            [first, second],
            [second, third],
            [first],
        ],
        rrf_k=60,
    )

    assert fused[0]["id"] == 1
    assert fused[0]["rrf_channels"] == 2
    assert fused[0]["rrf_score"] == pytest.approx(2 / 61)
    assert fused[1]["id"] == 2
    assert fused[1]["rrf_channels"] == 2


def test_finalize_keeps_two_chunks_per_document_and_top_k():
    candidates = []
    for chunk_id in range(1, 6):
        candidates.append(_candidate(chunk_id, document_id=1, content=f"同一文档 {chunk_id}"))
    candidates.append(_candidate(6, document_id=2, content="另一文档"))
    for index, item in enumerate(candidates):
        item["rrf_score"] = 1.0 / (index + 1)
        item["rrf_channels"] = 2

    results = finalize_results(candidates, top_k=3, max_chunks_per_doc=2)

    assert len(results) == 3
    assert [item["document_id"] for item in results] == [1, 1, 2]
    assert all(item["score_type"] == "rrf" for item in results)


def test_retrieve_runs_two_channels_for_three_queries_and_returns_ten(monkeypatch):
    calls: list[str] = []
    items = [
        _candidate(chunk_id, document_id=chunk_id)
        for chunk_id in range(1, 13)
    ]

    monkeypatch.setattr(retriever, "rewrite_query", lambda query: [query, f"{query} 变体1", f"{query} 变体2"])

    def vector_recall(*args, **kwargs):
        calls.append("vector")
        return [dict(item) for item in items]

    def keyword_recall(*args, **kwargs):
        calls.append("keyword")
        return [dict(item) for item in items]

    monkeypatch.setattr(retriever, "_vector_recall", vector_recall)
    monkeypatch.setattr(retriever, "keyword_search", keyword_recall)
    monkeypatch.setattr(retriever, "rerank", lambda query, candidates: (candidates, False))
    monkeypatch.setattr(retriever, "get_json", lambda key: None)
    monkeypatch.setattr(retriever, "set_json", lambda key, value, ttl: None)

    results = retriever.retrieve(object(), user_id=7, query="装饰器")

    assert calls.count("vector") == 3
    assert calls.count("keyword") == 3
    assert len(results) == 10
    assert results[0]["score_type"] == "rrf"


def test_query_rewrite_fallback_always_keeps_original_first(monkeypatch):
    query_rewrite.clear_query_cache()
    monkeypatch.setattr(query_rewrite, "_call_llm", lambda query: [])
    monkeypatch.setattr(query_rewrite, "get_json", lambda key: None)
    monkeypatch.setattr(query_rewrite, "set_json", lambda key, value, ttl: None)

    queries = query_rewrite.rewrite_query("装饰器怎么配置")

    assert queries[0] == "装饰器怎么配置"
    assert 2 <= len(queries) <= 3
    assert len(queries) == len(set(queries))


def test_rerank_filters_low_scores_and_falls_back_on_error(monkeypatch):
    candidates = [_candidate(1), _candidate(2)]
    monkeypatch.setattr(reranker, "_call_rerank", lambda query, items: [(0, 0.92), (1, 0.05)])

    reranked, used = reranker.rerank("查询", candidates)

    assert used is True
    assert [item["id"] for item in reranked] == [1]
    assert reranked[0]["rerank_score"] == pytest.approx(0.92)

    def fail(*args, **kwargs):
        raise RuntimeError("rerank unavailable")

    monkeypatch.setattr(reranker, "_call_rerank", fail)
    fallback, used = reranker.rerank("查询", candidates)
    assert used is False
    assert fallback == candidates


def test_document_chunk_uses_pgvector_and_search_text():
    assert isinstance(DocumentChunk.__table__.c.embedding.type, Vector)
    assert DocumentChunk.__table__.c.embedding.type.dim == 512
    assert DocumentChunk.__table__.c.search_text.nullable is False


def test_postgres_rag_indexes_use_required_parameters():
    hnsw_sql = " ".join(hnsw_index_sql().split())
    tsvector_sql = " ".join(tsvector_index_sql().split())

    assert "USING hnsw (embedding vector_cosine_ops)" in hnsw_sql
    assert "m = 24" in hnsw_sql
    assert "ef_construction = 200" in hnsw_sql
    assert settings.hnsw_ef_search == 100
    assert "USING gin (to_tsvector('simple', search_text))" in tsvector_sql


def test_redis_keys_are_user_scoped_and_ttls_match_document(monkeypatch):
    assert settings.rag_query_cache_ttl_seconds == 600
    assert settings.rag_result_cache_ttl_seconds == 60
    assert cache.search_cache_key(1, "同一问题", 10) != cache.search_cache_key(
        2, "同一问题", 10
    )

    class FakeRedis:
        def __init__(self):
            self.values = {}

        def setex(self, key, ttl, value):
            self.values[key] = (ttl, value)

        def get(self, key):
            item = self.values.get(key)
            return item[1] if item else None

    fake = FakeRedis()
    monkeypatch.setattr(cache, "_client", fake)
    monkeypatch.setattr(cache, "_client_initialized", True)
    cache.set_json("rag:test", {"ok": True}, 60)
    assert cache.get_json("rag:test") == {"ok": True}
    assert fake.values["rag:test"][0] == 60

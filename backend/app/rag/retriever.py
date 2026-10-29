"""混合检索：Query Rewrite + 向量/关键词双路召回 + RRF + Rerank。"""
from sqlalchemy.orm import Session

from app.config import settings
from app.rag.cache import get_json, search_cache_key, set_json
from app.rag.embedder import embed_query
from app.rag.fusion import finalize_results, reciprocal_rank_fusion
from app.rag.keyword_search import keyword_search
from app.rag.query_rewrite import rewrite_query
from app.rag.reranker import rerank
from app.rag.vector_search import vector_recall


def _vector_recall(
    db: Session,
    user_id: int,
    query: str,
    limit: int,
) -> list[dict]:
    query_vector = embed_query(query)
    return vector_recall(db, user_id, query_vector, limit)


def retrieve(db: Session, user_id: int, query: str, top_k: int | None = None) -> list[dict]:
    """混合检索当前用户资料，完整执行五步流程并返回 Top-K。"""
    effective_top_k = settings.rag_top_k if top_k is None else max(1, top_k)
    cache_key = search_cache_key(user_id, query, effective_top_k)
    cached = get_json(cache_key)
    if isinstance(cached, list):
        return cached

    recall_limit = max(effective_top_k * 2, settings.rag_recall_min)
    queries = rewrite_query(query)
    if not queries:
        return []

    ranked_lists: list[list[dict]] = []
    for search_query in queries:
        try:
            ranked_lists.append(_vector_recall(db, user_id, search_query, recall_limit))
        except Exception:  # noqa: BLE001
            # 向量通道失败时仍允许关键词通道完成检索
            ranked_lists.append([])
        try:
            ranked_lists.append(keyword_search(db, user_id, search_query, recall_limit))
        except Exception:  # noqa: BLE001
            ranked_lists.append([])

    fused = reciprocal_rank_fusion(ranked_lists)
    if not fused:
        return []
    rerank_candidates = fused[: effective_top_k * 2]
    reranked, used_rerank = rerank(query, rerank_candidates)
    results = finalize_results(
        reranked,
        top_k=effective_top_k,
        use_rerank_score=used_rerank,
    )
    set_json(cache_key, results, settings.rag_result_cache_ttl_seconds)
    return results

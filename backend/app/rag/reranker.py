"""智谱 Rerank 精排；未配置或调用失败时保留 RRF 排序。"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _call_rerank(query: str, candidates: list[dict]) -> list[tuple[int, float]]:
    if not settings.rerank_api_key:
        return []
    url = f"{settings.rerank_base_url.rstrip('/')}/rerank"
    payload = {
        "model": settings.rerank_model,
        "query": query,
        "documents": [item["content"][:4000] for item in candidates],
        "top_n": len(candidates),
        "return_documents": False,
    }
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {settings.rerank_api_key}"},
        json=payload,
        timeout=settings.rerank_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results") or data.get("data") or []
    ranked: list[tuple[int, float]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        index = result.get("index")
        score = result.get("relevance_score", result.get("score"))
        if isinstance(index, int) and isinstance(score, (int, float)):
            ranked.append((index, float(score)))
    return ranked


def rerank(query: str, candidates: list[dict]) -> tuple[list[dict], bool]:
    """返回精排候选及是否实际执行了 Rerank。"""
    if not candidates:
        return [], False
    try:
        ranked = _call_rerank(query, candidates)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rerank 失败，保持 RRF 排序: %s", exc)
        return candidates, False
    if not ranked:
        return candidates, False

    reranked: list[dict] = []
    for index, score in ranked:
        if not 0 <= index < len(candidates) or score < settings.rerank_min_score:
            continue
        item = dict(candidates[index])
        item["rerank_score"] = score
        reranked.append(item)
    reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    return reranked, True

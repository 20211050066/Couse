"""RAG Fusion 的查询改写：一个问题扩展为原始查询和两个检索变体。"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

import httpx

from app.config import settings
from app.rag.cache import get_json, query_rewrite_cache_key, set_json

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, list[str]]] = {}
_CACHE_LOCK = threading.Lock()

_SYNONYMS = {
    "怎么": "如何",
    "如何": "怎么",
    "配置": "设置",
    "设置": "配置",
    "原理": "工作机制",
    "区别": "差异",
    "报错": "错误",
    "作用": "用途",
    "为什么": "原因",
    "是什么": "含义",
}


def _cache_get(query: str) -> list[str] | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        item = _CACHE.get(query)
        if item is None:
            return None
        expires_at, variants = item
        if expires_at <= now:
            _CACHE.pop(query, None)
            return None
        return list(variants)


def _cache_set(query: str, variants: list[str]) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= 256:
            oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
            _CACHE.pop(oldest, None)
        _CACHE[query] = (time.monotonic() + settings.rag_query_cache_ttl_seconds, variants)


def clear_query_cache() -> None:
    """清空进程内查询改写缓存，供测试或配置变更后调用。"""
    with _CACHE_LOCK:
        _CACHE.clear()


def _clean_variants(raw: object, original: str) -> list[str]:
    variants: list[str] = []
    candidates = raw.get("queries", []) if isinstance(raw, dict) else raw
    if not isinstance(candidates, list):
        return variants
    for item in candidates:
        if not isinstance(item, str):
            continue
        variant = re.sub(r"\s+", " ", item).strip()
        if not variant or variant == original or variant in variants:
            continue
        variants.append(variant[:200])
        if len(variants) >= settings.rag_query_variants:
            break
    return variants


def _call_llm(query: str) -> list[str]:
    if not settings.deepseek_api_key:
        return []
    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    prompt = (
        "你是检索查询改写器。只输出 JSON 对象，格式为 "
        '{"queries":["变体1","变体2"]}。'
        "保留原问题的实体、术语和意图，用两种不同措辞生成两个简短检索查询；"
        "不要回答问题，不要添加解释。"
    )
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
        json=payload,
        timeout=8.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _clean_variants(json.loads(content), query)


def _fallback_variants(query: str) -> list[str]:
    """无可用 LLM 时生成低成本检索变体，保证多路召回链路仍可运行。"""
    from app.rag.keyword_search import tokenize_for_search

    variants: list[str] = []
    synonym_variant = query
    for source, target in _SYNONYMS.items():
        synonym_variant = synonym_variant.replace(source, target)
    if synonym_variant != query:
        variants.append(synonym_variant)

    tokens = tokenize_for_search(query)
    if len(tokens) > 1:
        variants.append(" ".join(tokens[:4]))
    if tokens:
        variants.append(" ".join(tokens[:2]) + " 定义 示例")

    unique: list[str] = []
    for variant in variants:
        variant = variant.strip()
        if variant and variant != query and variant not in unique:
            unique.append(variant)
        if len(unique) >= settings.rag_query_variants:
            break
    return unique


def rewrite_query(query: str) -> list[str]:
    """返回原始查询及最多两个改写变体；任何失败都保留原始查询。"""
    normalized = re.sub(r"\s+", " ", query).strip()
    if not normalized:
        return []

    cached = _cache_get(normalized)
    if cached is not None:
        return cached

    redis_key = query_rewrite_cache_key(normalized)
    redis_cached = get_json(redis_key)
    if (
        isinstance(redis_cached, list)
        and redis_cached
        and all(isinstance(item, str) for item in redis_cached)
    ):
        _cache_set(normalized, redis_cached)
        return redis_cached

    try:
        variants = _call_llm(normalized)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query Rewrite 失败，使用本地降级查询: %s", exc)
        variants = []
    if not variants:
        variants = _fallback_variants(normalized)

    queries = [normalized, *variants[: settings.rag_query_variants]]
    _cache_set(normalized, queries)
    set_json(redis_key, queries, settings.rag_query_cache_ttl_seconds)
    return queries

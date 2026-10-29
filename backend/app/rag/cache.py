"""Redis 缓存，用于 Query Rewrite（10 分钟）和检索结果（60 秒）。"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.config import settings

try:
    from redis import Redis
except ImportError:  # pragma: no cover - requirements 已声明
    Redis = None

logger = logging.getLogger(__name__)

_client = None
_client_initialized = False


def _get_client():
    global _client, _client_initialized
    if _client_initialized:
        return _client
    _client_initialized = True
    if Redis is None:
        return None
    try:
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 初始化失败，跳过缓存: %s", exc)
        _client = None
    return _client


def reset_client() -> None:
    """重置连接缓存，供配置变更或测试使用。"""
    global _client, _client_initialized
    _client = None
    _client_initialized = False


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def query_rewrite_cache_key(query: str) -> str:
    return f"rag:query-rewrite:{hash_key(query)}"


def search_cache_key(user_id: int, query: str, top_k: int) -> str:
    return f"rag:search:{user_id}:{hash_key(f'{query}|{top_k}')}"


def get_json(key: str) -> Any | None:
    client = _get_client()
    if client is None:
        return None
    try:
        value = client.get(key)
        return json.loads(value) if value is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 读取失败，跳过缓存: %s", exc)
        return None


def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 写入失败，跳过缓存: %s", exc)


def invalidate_user_search_cache(user_id: int) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        for key in client.scan_iter(match=f"rag:search:{user_id}:*", count=100):
            client.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 检索缓存失效失败: %s", exc)


def invalidate_all_search_cache() -> None:
    client = _get_client()
    if client is None:
        return
    try:
        for key in client.scan_iter(match="rag:search:*", count=100):
            client.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 全量检索缓存失效失败: %s", exc)

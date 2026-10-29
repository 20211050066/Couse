"""多路召回融合与最终结果整形。"""
from __future__ import annotations

from collections import defaultdict

from app.config import settings


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    rrf_k: int | None = None,
) -> list[dict]:
    """按 1 / (K + rank + 1) 融合任意数量的有序候选列表。"""
    smooth = settings.rag_rrf_k if rrf_k is None else rrf_k
    scores: dict[int, float] = defaultdict(float)
    candidates: dict[int, dict] = {}
    channels: dict[int, int] = defaultdict(int)

    for ranked in ranked_lists:
        seen_in_channel: set[int] = set()
        for rank, item in enumerate(ranked):
            chunk_id = int(item["id"])
            if chunk_id in seen_in_channel:
                continue
            seen_in_channel.add(chunk_id)
            scores[chunk_id] += 1.0 / (smooth + rank + 1)
            channels[chunk_id] += 1
            candidates.setdefault(chunk_id, item)

    fused = []
    for chunk_id, score in scores.items():
        item = dict(candidates[chunk_id])
        item["rrf_score"] = score
        item["rrf_channels"] = channels[chunk_id]
        fused.append(item)
    fused.sort(key=lambda item: item["rrf_score"], reverse=True)
    return fused


def finalize_results(
    candidates: list[dict],
    top_k: int,
    max_chunks_per_doc: int | None = None,
    use_rerank_score: bool = False,
) -> list[dict]:
    """按文档限制片段数并截断 Top-K，同时去除完全重复内容。"""
    max_per_doc = settings.rag_max_chunks_per_doc if max_chunks_per_doc is None else max_chunks_per_doc
    per_document: dict[int, int] = defaultdict(int)
    seen_content: set[str] = set()
    results: list[dict] = []

    for item in candidates:
        content_key = " ".join(item["content"].split())
        if content_key in seen_content:
            continue
        document_id = int(item["document_id"])
        if per_document[document_id] >= max_per_doc:
            continue
        seen_content.add(content_key)
        per_document[document_id] += 1

        score = item["rerank_score"] if use_rerank_score else item["rrf_score"]
        results.append(
            {
                "score": round(float(score), 4),
                "score_type": "rerank" if use_rerank_score else "rrf",
                "rrf_score": round(float(item["rrf_score"]), 4),
                "rrf_channels": item["rrf_channels"],
                "filename": item["filename"],
                "document_id": document_id,
                "chunk_index": item["chunk_index"],
                "content": item["content"][: settings.rag_source_char_limit],
            }
        )
        if len(results) >= top_k:
            break
    return results

"""中文关键词召回：Jieba 分词 + PostgreSQL tsvector/ts_rank_cd。"""
from __future__ import annotations

import re

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.document import CourseDocument, DocumentChunk

try:
    import jieba
except ImportError:  # pragma: no cover - requirements 已声明，保留无依赖降级
    jieba = None


STOPWORDS = {
    "的",
    "了",
    "是",
    "在",
    "和",
    "与",
    "及",
    "或",
    "而",
    "也",
    "都",
    "就",
    "还",
    "有",
    "我",
    "你",
    "他",
    "她",
    "它",
    "我们",
    "你们",
    "他们",
    "这",
    "那",
    "这个",
    "那个",
    "一个",
    "一些",
    "什么",
    "怎么",
    "如何",
    "为什么",
    "可以",
    "能够",
    "需要",
    "进行",
    "通过",
    "对于",
    "关于",
    "以及",
    "但是",
    "如果",
    "因为",
    "所以",
    "然后",
    "已经",
    "没有",
    "不是",
    "比较",
    "非常",
    "一下",
    "请问",
    "请",
    "吗",
    "呢",
    "吧",
    "啊",
    "呀",
    "着",
    "过",
    "地",
    "得",
}


def tokenize_for_search(text: str, deduplicate: bool = True) -> list[str]:
    """使用 cut_for_search 生成词元，过滤虚词并保留领域单字。"""
    normalized = text.lower().strip()
    if not normalized:
        return []
    cut_for_search = getattr(jieba, "cut_for_search", None)
    if callable(cut_for_search):
        raw_tokens = list(cut_for_search(normalized))
    else:
        raw_tokens = re.findall(r"[\u3400-\u9fff]|[a-z0-9_]+", normalized)

    tokens: list[str] = []
    for token in raw_tokens:
        token = token.strip().lower()
        if not token or token in STOPWORDS or re.fullmatch(r"[\W_]+", token):
            continue
        if not deduplicate or token not in tokens:
            tokens.append(token)
    return tokens


def keyword_search(
    db: Session,
    user_id: int,
    query: str,
    limit: int,
) -> list[dict]:
    """在当前用户已就绪资料中执行宽召回，再按 OR/AND 覆盖度重排。"""
    terms = tokenize_for_search(query)
    if not terms or limit <= 0:
        return []

    def tsquery_text(operator: str) -> str:
        quoted = [f'"{term.replace(chr(34), "")}"' for term in terms]
        return f" {operator} ".join(quoted)

    search_vector = func.to_tsvector(
        "simple",
        func.coalesce(DocumentChunk.search_text, ""),
    )
    or_query = func.to_tsquery("simple", tsquery_text("|"))
    and_query = func.to_tsquery("simple", tsquery_text("&"))
    rank = func.ts_rank_cd(search_vector, or_query)
    and_bonus = case((search_vector.op("@@")(and_query), 0.5), else_=0.0)
    exact_bonus = case(
        (DocumentChunk.content.contains(query, autoescape=True), 1.0),
        else_=0.0,
    )
    keyword_score = (rank + and_bonus + exact_bonus).label("keyword_score")
    rows = (
        db.query(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            CourseDocument.filename,
            DocumentChunk.content,
            keyword_score,
        )
        .join(CourseDocument, DocumentChunk.document_id == CourseDocument.id)
        .filter(
            CourseDocument.user_id == user_id,
            CourseDocument.status == "ready",
            search_vector.op("@@")(or_query),
        )
        .order_by(keyword_score.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": chunk_id,
            "document_id": document_id,
            "chunk_index": chunk_index,
            "filename": filename,
            "content": content,
            "keyword_score": float(keyword_score),
        }
        for chunk_id, document_id, chunk_index, filename, content, keyword_score in rows
    ]

"""doc_type 필터 강제 RAG 저장/검색 엔진 v2 (Parent/Child 청킹 · HNSW · 2-gram BM25+RRF · MMR · Rewrite/HyDE)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
import logging
import math
import re
from typing import Any, Literal

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bedrock import ainvoke_tracked, embed_text, get_fast_llm
from app.core.chunker import build_source_label, split_into_chunks
from app.core.database import VectorDocument
from app.prompts import build_chat_prompt

logger = logging.getLogger(__name__)

SearchStrategy = Literal["basic", "hybrid", "rewrite", "hyde"]

_HANGUL_WORD_RE = re.compile(r"[가-힣]+")
_ALNUM_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._/%+-][a-z0-9]+)*")


class DocType(StrEnum):
    EXPERIENCE = "experience"
    CAREER_IDENTITY = "career_identity"
    COMPANY_RESEARCH = "company_research"
    INTEREST_CLIP = "interest_clip"
    JASOSEO_SAMPLE = "jasoseo_sample"


@dataclass(slots=True)
class VectorSearchHit:
    id: int
    doc_type: str
    ref_id: str
    content: str
    metadata: dict[str, Any]
    distance: float
    similarity: float
    source_label: str = ""
    strategy_used: str = "basic"
    effective_query: str = ""
    rrf_score: float | None = None


def validate_doc_types(doc_types: list[str] | list[DocType]) -> list[str]:
    """필터 없는 전체 벡터 검색을 원천 차단하고 허용된 5종 Enum만 통과시킨다."""
    if not doc_types:
        raise ValueError("doc_types must be a non-empty list to enforce RAG isolation.")
    validated: list[str] = []
    for dt in doc_types:
        validated.append(DocType(dt).value)
    return validated


# ==============================================================================
# Korean 2-gram Tokenizer, BM25, RRF & MMR (Unit 5)
# ==============================================================================
def tokenize_korean_2gram(text: str) -> list[str]:
    """한국어 문자 2-gram + 영문·숫자 기술 용어 혼합 토크나이저 (띄어쓰기/조사 변화에 강함)."""
    lowered = (text or "").lower()
    tokens: list[str] = []

    for word in _HANGUL_WORD_RE.findall(lowered):
        if len(word) == 1:
            tokens.append(word)
        else:
            tokens.append(word)
            for i in range(len(word) - 1):
                tokens.append(word[i : i + 2])

    tokens.extend(_ALNUM_TOKEN_RE.findall(lowered))
    return tokens


def compute_bm25_scores(
    query: str,
    documents: list[tuple[str, str]],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> dict[str, float]:
    """Okapi BM25 점수 계산. documents는 (doc_key, text) 리스트."""
    q_tokens = tokenize_korean_2gram(query)
    if not q_tokens or not documents:
        return {}

    doc_tfs: dict[str, Counter[str]] = {}
    doc_lens: dict[str, int] = {}
    df: Counter[str] = Counter()

    for key, text in documents:
        toks = tokenize_korean_2gram(text)
        tf = Counter(toks)
        doc_tfs[key] = tf
        doc_lens[key] = len(toks)
        for unique_tok in tf.keys():
            df[unique_tok] += 1

    n_docs = len(documents)
    avgdl = sum(doc_lens.values()) / max(1, n_docs)

    scores: dict[str, float] = {}
    unique_q = list(dict.fromkeys(q_tokens))
    for key, tf in doc_tfs.items():
        dl = doc_lens[key]
        if dl == 0:
            scores[key] = 0.0
            continue
        score = 0.0
        for tok in unique_q:
            freq = tf.get(tok, 0)
            if freq == 0:
                continue
            doc_freq = df.get(tok, 0)
            idf = math.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))
            denom = freq + k1 * (1.0 - b + b * (dl / max(1e-9, avgdl)))
            score += idf * (freq * (k1 + 1.0)) / denom
        scores[key] = score
    return scores


def reciprocal_rank_fusion(
    vector_ranked_keys: list[str],
    bm25_ranked_keys: list[str],
    *,
    k: int = 60,
    vector_weight: float = 1.0,
    bm25_weight: float = 1.0,
) -> dict[str, float]:
    """벡터 순위와 BM25 순위를 Reciprocal Rank Fusion으로 결합한다."""
    fused: dict[str, float] = {}
    for rank, key in enumerate(vector_ranked_keys, start=1):
        fused[key] = fused.get(key, 0.0) + vector_weight / (k + rank)
    for rank, key in enumerate(bm25_ranked_keys, start=1):
        fused[key] = fused.get(key, 0.0) + bm25_weight / (k + rank)
    return fused


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        fa = float(a)
        fb = float(b)
        dot += fa * fb
        norm_a += fa * fa
        norm_b += fb * fb
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def mmr_rerank(
    query_vector: list[float],
    candidates: list[tuple[VectorSearchHit, list[float]]],
    *,
    top_k: int,
    lambda_mult: float = 0.65,
) -> list[VectorSearchHit]:
    """Maximal Marginal Relevance 재정렬: 관련성과 프로젝트/청크 간 다양성을 균형화한다."""
    if not candidates or top_k <= 0:
        return []
    if len(candidates) <= 1:
        return [candidates[0][0]]

    # 쿼리 유사도 사전 계산
    q_sims = [_cosine_similarity(query_vector, vec) for _, vec in candidates]
    selected_indices: list[int] = []
    remaining = list(range(len(candidates)))

    while remaining and len(selected_indices) < top_k:
        best_idx = remaining[0]
        best_score = -1e9
        for idx in remaining:
            rel = q_sims[idx]
            if not selected_indices:
                mmr_score = rel
            else:
                max_sim_to_selected = max(
                    _cosine_similarity(candidates[idx][1], candidates[s][1])
                    for s in selected_indices
                )
                mmr_score = lambda_mult * rel - (1.0 - lambda_mult) * max_sim_to_selected
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return [candidates[i][0] for i in selected_indices]


# ==============================================================================
# Query Rewriting & HyDE (Unit 5 & Unit 8)
# ==============================================================================
async def rewrite_search_query(query: str) -> str:
    """Fast LLM으로 사용자 질문을 포트폴리오 문서 용어 중심의 검색 쿼리로 재작성한다."""
    clean = (query or "").strip()
    if not clean:
        return clean
    try:
        llm = get_fast_llm(temperature=0.1, max_tokens=200)
        messages = build_chat_prompt(
            "query_rewrite",
            "원본 질문: {query}",
            human_vars={"query": clean},
        )
        ai_msg = await ainvoke_tracked(llm, messages, caller="rag:query_rewrite")
        rewritten = (
            ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
        ).strip().splitlines()[0].strip(" \"'")
        return rewritten if rewritten else clean
    except Exception as exc:
        logger.warning("Query rewrite failed, falling back to original query: %s", exc)
        return clean


async def generate_hyde_document(query: str) -> str:
    """HyDE(Hypothetical Document Embeddings): 검색 전용 가상 답변 문서를 생성한다."""
    clean = (query or "").strip()
    if not clean:
        return clean
    try:
        llm = get_fast_llm(temperature=0.2, max_tokens=320)
        messages = build_chat_prompt(
            "hyde_generate",
            "사용자 질문: {query}",
            human_vars={"query": clean},
        )
        ai_msg = await ainvoke_tracked(llm, messages, caller="rag:hyde_generate")
        hypothetical = (
            ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
        ).strip()
        return hypothetical if hypothetical else clean
    except Exception as exc:
        logger.warning("HyDE generation failed, falling back to original query: %s", exc)
        return clean


# ==============================================================================
# Upsert / Delete (Parent/Child Chunking + Session Safety)
# ==============================================================================
async def upsert_document(
    session: AsyncSession,
    *,
    doc_type: str | DocType,
    ref_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
    chunk: bool = True,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
) -> int:
    """(doc_type, ref_id) 기준으로 벡터 문서를 Parent/Child 청킹 업서트하고 대표 ID를 반환한다."""
    validated_type = DocType(doc_type).value
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("Cannot upsert empty content into vector_documents.")

    parent_ref = str(ref_id).strip()[:88]
    base_meta = dict(metadata or {})

    # 단일 임베딩이 직접 주입되었거나 chunk=False이면 단일 행으로 저장 (기존 호환/베이스라인 비교)
    if embedding is not None or not chunk:
        vector = embedding if embedding is not None else await embed_text(clean_content)
        source_label = build_source_label(validated_type, parent_ref, base_meta)
        doc_meta = {
            **base_meta,
            "parent_ref_id": parent_ref,
            "chunk_index": 0,
            "chunk_total": 1,
            "source_label": source_label,
        }
        table = VectorDocument.__table__
        insert_stmt = pg_insert(table).values(
            doc_type=validated_type,
            ref_id=parent_ref,
            content=clean_content,
            metadata=doc_meta,
            embedding=vector,
        )
        stmt = insert_stmt.on_conflict_do_update(
            constraint="uq_vector_documents_doc_type_ref_id",
            set_={
                "content": insert_stmt.excluded.content,
                "metadata": insert_stmt.excluded.metadata,
                "embedding": insert_stmt.excluded.embedding,
            },
        ).returning(table.c.id)
        result = await session.execute(stmt)
        await session.commit()
        return int(result.scalar_one())

    chunks = split_into_chunks(
        clean_content,
        doc_type=validated_type,
        ref_id=parent_ref,
        metadata=base_meta,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    embedded_rows: list[tuple[Any, list[float]]] = []
    for ch in chunks:
        vec = await embed_text(ch.content)
        embedded_rows.append((ch, vec))

    return await _write_chunked_rows(
        session,
        validated_type=validated_type,
        parent_ref=parent_ref,
        base_meta=base_meta,
        embedded_rows=embedded_rows,
    )


async def _write_chunked_rows(
    session: AsyncSession,
    *,
    validated_type: str,
    parent_ref: str,
    base_meta: dict[str, Any],
    embedded_rows: list[tuple[Any, list[float]]],
) -> int:
    """기존 parent 및 자식 청크를 정리하고 새 청크 세트를 원자적으로 업서트한다."""
    del_stmt = delete(VectorDocument).where(
        VectorDocument.doc_type == validated_type,
        or_(
            VectorDocument.ref_id == parent_ref,
            VectorDocument.ref_id.like(f"{parent_ref}::c%"),
        ),
    )
    await session.execute(del_stmt)

    table = VectorDocument.__table__
    first_id = 0
    for ch, vec in embedded_rows:
        chunk_meta = {
            **base_meta,
            "parent_ref_id": ch.parent_ref_id,
            "chunk_index": ch.chunk_index,
            "chunk_total": ch.chunk_total,
            "section_header": ch.section_header,
            "source_label": ch.source_label,
        }
        insert_stmt = pg_insert(table).values(
            doc_type=validated_type,
            ref_id=ch.ref_id,
            content=ch.content,
            metadata=chunk_meta,
            embedding=vec,
        )
        stmt = insert_stmt.on_conflict_do_update(
            constraint="uq_vector_documents_doc_type_ref_id",
            set_={
                "content": insert_stmt.excluded.content,
                "metadata": insert_stmt.excluded.metadata,
                "embedding": insert_stmt.excluded.embedding,
            },
        ).returning(table.c.id)
        res = await session.execute(stmt)
        row_id = int(res.scalar_one())
        if first_id == 0:
            first_id = row_id

    await session.commit()
    return first_id


async def try_upsert_document(
    session: AsyncSession,
    *,
    doc_type: str | DocType,
    ref_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    chunk: bool = True,
) -> bool:
    """정형 DB 저장 후 벡터 동기화를 시도하고 성공 여부를 반환한다.

    모든 청크 임베딩을 DB 쓰기보다 먼저 수행해 Bedrock 장애 시
    호출자의 SQLAlchemy 세션(ORM 인스턴스)이 rollback으로 만료되지 않게 보호한다.
    """
    clean_content = content.strip()
    if not clean_content:
        return False

    validated_type = DocType(doc_type).value
    parent_ref = str(ref_id).strip()[:88]
    base_meta = dict(metadata or {})

    try:
        if chunk:
            chunks = split_into_chunks(
                clean_content,
                doc_type=validated_type,
                ref_id=parent_ref,
                metadata=base_meta,
            )
            embedded_rows = [(ch, await embed_text(ch.content)) for ch in chunks]
        else:
            single_vec = await embed_text(clean_content)
            embedded_rows = []
    except Exception as exc:
        logger.warning(
            "Vector embedding skipped/failed for (%s, %s): %s", doc_type, ref_id, exc
        )
        return False

    try:
        if chunk:
            await _write_chunked_rows(
                session,
                validated_type=validated_type,
                parent_ref=parent_ref,
                base_meta=base_meta,
                embedded_rows=embedded_rows,
            )
        else:
            await upsert_document(
                session,
                doc_type=validated_type,
                ref_id=parent_ref,
                content=clean_content,
                metadata=base_meta,
                embedding=single_vec,
                chunk=False,
            )
        return True
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "Vector upsert DB write failed for (%s, %s): %s", doc_type, ref_id, exc
        )
        return False


async def delete_document(
    session: AsyncSession,
    *,
    doc_type: str | DocType,
    ref_id: str,
) -> None:
    """정형 데이터 삭제 시 연결된 부모·자식 벡터 청크를 모두 함께 정리한다."""
    validated_type = DocType(doc_type).value
    parent_ref = str(ref_id).strip()
    stmt = delete(VectorDocument).where(
        VectorDocument.doc_type == validated_type,
        or_(
            VectorDocument.ref_id == parent_ref,
            VectorDocument.ref_id.like(f"{parent_ref}::c%"),
        ),
    )
    await session.execute(stmt)
    await session.commit()


# ==============================================================================
# Search Engine v2 (basic / hybrid / rewrite / hyde + max_distance + MMR)
# ==============================================================================
async def search_documents(
    session: AsyncSession,
    *,
    query: str,
    doc_types: list[str] | list[DocType],
    top_k: int = 5,
    metadata_filter: dict[str, Any] | None = None,
    strategy: SearchStrategy = "basic",
    max_distance: float | None = None,
    use_mmr: bool = False,
    mmr_lambda: float = 0.65,
    fetch_k: int | None = None,
) -> list[VectorSearchHit]:
    """doc_types 필터를 강제한 다전략 RAG 검색 엔진.

    - basic: 질문 원문 코사인 유사도 검색
    - hybrid: 코사인 유사도 + 한국어 2-gram BM25 → RRF 결합
    - rewrite: Fast LLM 질문 재작성 후 하이브리드/벡터 검색
    - hyde: Fast LLM 가상 답변(HyDE) 임베딩 기반 벡터 검색 (가상 답변은 즉시 폐기)
    - max_distance: 지정 시 해당 코사인 거리 초과 노이즈 조각 제거
    - use_mmr: 후보군에서 유사도×다양성(MMR) 재정렬
    """
    validated_types = validate_doc_types(doc_types)
    effective_query = query.strip()

    if strategy == "rewrite":
        effective_query = await rewrite_search_query(effective_query)
    elif strategy == "hyde":
        effective_query = await generate_hyde_document(effective_query)

    query_vector = await embed_text(effective_query)

    candidate_limit = fetch_k or (max(top_k * 4, 15) if (strategy == "hybrid" or use_mmr) else top_k)
    distance_expr = VectorDocument.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(VectorDocument, distance_expr)
        .where(VectorDocument.doc_type.in_(validated_types))
        .order_by(distance_expr.asc())
        .limit(candidate_limit)
    )

    if metadata_filter:
        stmt = stmt.where(VectorDocument.doc_metadata.contains(metadata_filter))

    rows = (await session.execute(stmt)).all()

    candidates: list[tuple[VectorSearchHit, list[float]]] = []
    for doc, distance in rows:
        dist_val = float(distance) if distance is not None else 1.0
        if max_distance is not None and dist_val > max_distance:
            continue
        meta = doc.doc_metadata or {}
        label = str(
            meta.get("source_label")
            or build_source_label(doc.doc_type, doc.ref_id, meta)
        )
        hit = VectorSearchHit(
            id=doc.id,
            doc_type=doc.doc_type,
            ref_id=doc.ref_id,
            content=doc.content,
            metadata=meta,
            distance=dist_val,
            similarity=max(0.0, 1.0 - dist_val),
            source_label=label,
            strategy_used=strategy,
            effective_query=effective_query if strategy != "hyde" else f"[HyDE] {query.strip()}",
        )
        vec_list = list(doc.embedding) if doc.embedding is not None else []
        candidates.append((hit, vec_list))

    # Hybrid Search: doc_types 격리 풀 전체(최대 300개)에서 2-gram BM25 결합 → RRF
    if strategy == "hybrid":
        pool_stmt = (
            select(VectorDocument)
            .where(VectorDocument.doc_type.in_(validated_types))
            .limit(300)
        )
        if metadata_filter:
            pool_stmt = pool_stmt.where(VectorDocument.doc_metadata.contains(metadata_filter))
        pool_docs = (await session.execute(pool_stmt)).scalars().all()

        bm25_scores = compute_bm25_scores(
            query,
            [(str(d.id), d.content) for d in pool_docs],
        )
        bm25_ranked = [
            key
            for key, score in sorted(
                bm25_scores.items(), key=lambda kv: kv[1], reverse=True
            )
            if score > 0.0
        ]
        vec_ranked = [str(hit.id) for hit, _ in candidates]
        rrf_map = reciprocal_rank_fusion(vec_ranked, bm25_ranked, k=60)

        # BM25 상위에만 걸린 문서도 max_distance 여유 조건으로 후보 풀에 보강
        by_id: dict[str, tuple[VectorSearchHit, list[float]]] = {
            str(hit.id): (hit, vec) for hit, vec in candidates
        }
        for d in pool_docs:
            key = str(d.id)
            if key not in by_id and bm25_scores.get(key, 0.0) > 0.0:
                vec_list = list(d.embedding) if d.embedding is not None else []
                sim = _cosine_similarity(query_vector, vec_list) if vec_list else 0.0
                dist_val = max(0.0, 1.0 - sim)
                if max_distance is not None and dist_val > min(0.95, max_distance + 0.12):
                    continue
                meta = d.doc_metadata or {}
                label = str(
                    meta.get("source_label")
                    or build_source_label(d.doc_type, d.ref_id, meta)
                )
                by_id[key] = (
                    VectorSearchHit(
                        id=d.id,
                        doc_type=d.doc_type,
                        ref_id=d.ref_id,
                        content=d.content,
                        metadata=meta,
                        distance=dist_val,
                        similarity=max(0.0, sim),
                        source_label=label,
                        strategy_used="hybrid",
                        effective_query=effective_query,
                    ),
                    vec_list,
                )

        merged: list[tuple[VectorSearchHit, list[float]]] = []
        for key, (hit, vec) in by_id.items():
            hit.rrf_score = rrf_map.get(key, 0.0)
            merged.append((hit, vec))
        merged.sort(key=lambda pair: (pair[0].rrf_score or 0.0, pair[0].similarity), reverse=True)
        candidates = merged[:candidate_limit]

    if use_mmr and len(candidates) > top_k:
        return mmr_rerank(query_vector, candidates, top_k=top_k, lambda_mult=mmr_lambda)

    return [hit for hit, _ in candidates[:top_k]]


def format_hits_with_citations(
    hits: list[VectorSearchHit],
    *,
    max_chars_per_hit: int = 600,
) -> str:
    """검색 조각에 표준 출처 태그(`[출처: ...]`)를 붙여 프롬프트 `<context>`용 문자열을 만든다."""
    if not hits:
        return "(관련 문서를 찾지 못했습니다.)"
    blocks: list[str] = []
    for idx, hit in enumerate(hits, start=1):
        label = hit.source_label or build_source_label(hit.doc_type, hit.ref_id, hit.metadata)
        snippet = hit.content.strip()[:max_chars_per_hit]
        blocks.append(
            f"[{idx}] [출처: {label} | 유사도 {hit.similarity:.2f}]\n{snippet}"
        )
    return "\n\n".join(blocks)

"""Parent/Child 문서 청킹 및 출처 메타데이터(Provenance) 표준화 모듈 (Unit 3~5)."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

try:
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )
except ImportError:  # pragma: no cover - 오프라인 로컬 fallback
    MarkdownHeaderTextSplitter = None  # type: ignore[assignment]
    RecursiveCharacterTextSplitter = None  # type: ignore[assignment]


DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_MIN_CHUNK_THRESHOLD = 620

_MD_HEADER_RE = re.compile(r"(?m)^#{1,3}\s+.+")


@dataclass(slots=True)
class TextChunk:
    chunk_index: int
    chunk_total: int
    ref_id: str
    parent_ref_id: str
    content: str
    section_header: str
    source_label: str


def build_source_label(
    doc_type: str,
    ref_id: str,
    metadata: dict[str, Any] | None = None,
    section_header: str = "",
) -> str:
    """검색 결과 인용에 쓰이는 사람이 읽기 쉬운 출처 라벨을 생성한다."""
    meta = metadata or {}
    if meta.get("source_label"):
        base = str(meta["source_label"]).strip()
    elif doc_type == "experience":
        proj_name = str(meta.get("project_name") or "").strip()
        sec_title = str(meta.get("section_title") or meta.get("title") or "").strip()
        if proj_name and sec_title:
            base = f"프로젝트: {proj_name} > {sec_title}"
        elif sec_title:
            base = f"STAR-L 경험: {sec_title}"
        else:
            base = f"경험({ref_id})"
    elif doc_type == "company_research":
        company = str(meta.get("company_name") or "").strip()
        role = str(meta.get("target_role") or "").strip()
        base = f"기업 리서치: {company}" + (f" ({role})" if role else "") if company else f"기업({ref_id})"
    elif doc_type == "career_identity":
        title = str(meta.get("source_title") or meta.get("title") or "").strip()
        base = f"신념/회고: {title}" if title else "커리어 신념·비전"
    elif doc_type == "jasoseo_sample":
        company = str(meta.get("company") or meta.get("company_name") or "샘플").strip()
        q = str(meta.get("question_type") or meta.get("title") or "").strip()
        base = f"자소서 레퍼런스: {company}" + (f" - {q}" if q else "")
    else:
        base = f"{doc_type}:{ref_id}"

    if section_header and section_header not in base:
        return f"{base} / {section_header}"
    return base


def _fallback_recursive_split(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """langchain-text-splitters 미설치 환경용 순수 Python 폴백 분할기."""
    clean = text.strip()
    if len(clean) <= chunk_size:
        return [clean] if clean else []
    chunks: list[str] = []
    step = max(1, chunk_size - chunk_overlap)
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        piece = clean[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(clean):
            break
        start += step
    return chunks


def split_into_chunks(
    content: str,
    *,
    doc_type: str,
    ref_id: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk_threshold: int = DEFAULT_MIN_CHUNK_THRESHOLD,
) -> list[TextChunk]:
    """장문은 MarkdownHeader + RecursiveCharacterTextSplitter(500/100)로 Parent/Child 분할한다.

    단문(<= min_chunk_threshold)은 불필요한 파편화를 막기 위해 원본 ref_id 단일 청크로 유지한다.
    """
    clean = (content or "").strip()
    if not clean:
        return []

    parent_ref_id = str(ref_id).strip()[:88]
    meta = metadata or {}

    if len(clean) <= min_chunk_threshold:
        label = build_source_label(doc_type, parent_ref_id, meta)
        return [
            TextChunk(
                chunk_index=0,
                chunk_total=1,
                ref_id=parent_ref_id,
                parent_ref_id=parent_ref_id,
                content=clean,
                section_header="",
                source_label=label,
            )
        ]

    # 1단계: 마크다운 헤더가 있으면 의미 경계로 1차 분할
    raw_segments: list[tuple[str, str]] = []  # (section_header, segment_text)
    if MarkdownHeaderTextSplitter is not None and _MD_HEADER_RE.search(clean):
        header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "h1"),
                ("##", "h2"),
                ("###", "h3"),
            ],
            strip_headers=False,
        )
        md_docs = header_splitter.split_text(clean)
        for d in md_docs:
            hdr_parts = [
                str(d.metadata.get(k)).strip()
                for k in ("h1", "h2", "h3")
                if d.metadata.get(k)
            ]
            raw_segments.append((" > ".join(hdr_parts), d.page_content.strip()))
    else:
        raw_segments.append(("", clean))

    # 2단계: 각 세그먼트를 RecursiveCharacterTextSplitter(500자, 겹침 100자)로 세밀 분할
    if RecursiveCharacterTextSplitter is not None:
        char_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", "다. ", " ", ""],
            length_function=len,
        )
        split_fn = char_splitter.split_text
    else:
        split_fn = lambda txt: _fallback_recursive_split(txt, chunk_size, chunk_overlap)

    pieces: list[tuple[str, str]] = []
    for sec_header, seg_text in raw_segments:
        if not seg_text:
            continue
        for sub in split_fn(seg_text):
            sub_clean = sub.strip()
            if sub_clean:
                pieces.append((sec_header, sub_clean))

    if not pieces:
        pieces = [("", clean)]

    total = len(pieces)
    result: list[TextChunk] = []
    for idx, (sec_header, text_piece) in enumerate(pieces):
        chunk_ref = parent_ref_id if total == 1 else f"{parent_ref_id}::c{idx}"
        label = build_source_label(doc_type, parent_ref_id, meta, section_header=sec_header)
        result.append(
            TextChunk(
                chunk_index=idx,
                chunk_total=total,
                ref_id=chunk_ref[:100],
                parent_ref_id=parent_ref_id,
                content=text_piece,
                section_header=sec_header,
                source_label=label,
            )
        )
    return result

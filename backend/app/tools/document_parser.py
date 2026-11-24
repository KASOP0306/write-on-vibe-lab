"""포트폴리오 업데이트용 다중 포맷 문서 파서 (.pdf, .docx, .pptx, .ipynb, .md, .txt, 코드)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
MAX_EXTRACTED_CHARS = 28000

TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".sh",
    ".csv",
    ".html",
    ".css",
    ".dockerfile",
}


class DocumentParseError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _parse_pdf(data: bytes) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError(
            "PDF 파서(pypdf)가 설치되지 않았습니다.", status_code=500
        ) from exc

    reader = PdfReader(io.BytesIO(data))
    pages_text: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        extracted = (page.extract_text() or "").strip()
        if extracted:
            pages_text.append(f"[Page {idx}]\n{extracted}")
    return "\n\n".join(pages_text), f"{len(reader.pages)} pages"


def _parse_docx(data: bytes) -> tuple[str, str]:
    try:
        from docx import Document
    except ImportError as exc:
        raise DocumentParseError(
            "DOCX 파서(python-docx)가 설치되지 않았습니다.", status_code=500
        ) from exc

    doc = Document(io.BytesIO(data))
    blocks: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            blocks.append(text)
    for table in doc.tables:
        rows_txt = []
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                rows_txt.append(" | ".join(cells))
        if rows_txt:
            blocks.append("[표]\n" + "\n".join(rows_txt))
    return "\n\n".join(blocks), f"{len(doc.paragraphs)} paragraphs"


def _parse_pptx(data: bytes) -> tuple[str, str]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise DocumentParseError(
            "PPTX 파서(python-pptx)가 설치되지 않았습니다.", status_code=500
        ) from exc

    prs = Presentation(io.BytesIO(data))
    slides_text: list[str] = []
    for idx, slide in enumerate(prs.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                txt = shape.text_frame.text.strip()
                if txt:
                    parts.append(txt)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
        if parts:
            slides_text.append(f"[Slide {idx}]\n" + "\n".join(parts))
    return "\n\n".join(slides_text), f"{len(prs.slides)} slides"


def _parse_ipynb(data: bytes) -> tuple[str, str]:
    try:
        nb = json.loads(_decode_bytes(data))
    except json.JSONDecodeError as exc:
        raise DocumentParseError(
            "올바른 Jupyter Notebook(.ipynb) JSON 형식이 아닙니다."
        ) from exc

    cells = nb.get("cells") or []
    blocks: list[str] = []
    for idx, cell in enumerate(cells, start=1):
        ctype = cell.get("cell_type")
        source = cell.get("source") or []
        text = "".join(source) if isinstance(source, list) else str(source)
        text = text.strip()
        if not text:
            continue
        if ctype == "markdown":
            blocks.append(f"[Notebook Markdown {idx}]\n{text}")
        elif ctype == "code":
            blocks.append(f"[Notebook Code {idx}]\n```\n{text[:1500]}\n```")
    return "\n\n".join(blocks), f"{len(cells)} cells"


def parse_uploaded_file(filename: str, data: bytes) -> dict[str, Any]:
    """업로드된 파일 바이트를 텍스트로 변환해 구조화 메타정보와 함께 반환한다."""
    if not data:
        raise DocumentParseError("비어 있는 파일입니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentParseError("파일 크기는 최대 15MB까지 지원합니다.", status_code=413)

    clean_name = Path(filename or "document.txt").name
    ext = Path(clean_name).suffix.lower()
    file_format = ext.lstrip(".") or "txt"

    if ext == ".pdf":
        text, info = _parse_pdf(data)
    elif ext == ".docx":
        text, info = _parse_docx(data)
    elif ext == ".pptx":
        text, info = _parse_pptx(data)
    elif ext == ".ipynb":
        text, info = _parse_ipynb(data)
    elif ext in TEXT_EXTENSIONS or clean_name.lower() == "dockerfile":
        text = _decode_bytes(data)
        info = f"{len(text.splitlines())} lines"
    else:
        raise DocumentParseError(
            f"지원하지 않는 파일 형식({ext or '확장자 없음'})입니다. "
            "지원 형식: .pdf, .docx, .pptx, .md, .txt, .ipynb, 주요 코드/설정 파일"
        )

    clean_text = text.strip()
    if len(clean_text) < 10:
        raise DocumentParseError(
            "문서에서 유의미한 텍스트를 추출하지 못했습니다. (스캔 이미지 PDF인 경우 텍스트를 직접 붙여넣어 주세요.)"
        )

    return {
        "filename": clean_name,
        "file_format": file_format,
        "text": clean_text[:MAX_EXTRACTED_CHARS],
        "raw_char_count": len(clean_text),
        "info": info,
    }

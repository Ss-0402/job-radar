"""把上传的简历文件转成纯文本。支持 .txt / .md / .docx / .pdf。

真实简历大多是 PDF 或 Word，所以这里不做“请先转成 txt”这种要求。
解析失败或读不到文字（扫描件）时返回明确的提示，不抛异常。
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

SUPPORTED = ["txt", "md", "docx", "pdf"]

MAX_CHARS = 20_000      # 解析后截断，避免超长文档占内存
MIN_CHARS = 30          # 少于这个长度认为没读到内容（扫描件/空文档）


def _from_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:               # 简历常用表格排版
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _from_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _clean(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def to_text(filename: str, data: bytes) -> tuple[bool, str]:
    """返回 (成功, 文本或错误提示)。"""
    suffix = Path(filename or "").suffix.lower().lstrip(".")

    if suffix in ("txt", "md", ""):
        text = data.decode("utf-8", errors="ignore")
    elif suffix == "docx":
        try:
            text = _from_docx(data)
        except Exception:
            return False, "这个 Word 文件解析失败：如果是旧版 .doc，请另存为 .docx 再上传"
    elif suffix == "pdf":
        try:
            text = _from_pdf(data)
        except Exception:
            return False, "这个 PDF 解析失败：可能设置了打开密码或文件已损坏"
    else:
        return False, f"暂不支持 .{suffix} 格式，请上传 txt / docx / pdf"

    text = _clean(text)
    if len(text) < MIN_CHARS:
        return False, (
            "没能从这个文件里读到文字（扫描件或图片型 PDF 常见），"
            "请换成可复制文字的版本，或直接把内容粘贴到下面的输入框"
        )
    return True, text[:MAX_CHARS]

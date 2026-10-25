"""Safe, bounded-memory attachment extraction. Original file always remains intact.

Extracted text is a separate UTF-8 sidecar; binary bytes are NEVER stored in
PostgreSQL TEXT. If extraction can't finish, report that explicitly and retain
the original for targeted tool analysis (no silent omission).
"""
import csv
import io
import json
import zipfile
from pathlib import Path

MAX_EXTRACTED_BYTES = 64 * 1024 * 1024


class ExtractionLimit(Exception):
    pass


class _Sink:
    def __init__(self, path: Path, budget: int):
        self.file = path.open("w", encoding="utf-8", newline="\n")
        self.budget = budget
        self.written = 0

    def write(self, text: str) -> None:
        clean = str(text).replace("\x00", "\ufffd")
        encoded = clean.encode("utf-8")
        if self.written + len(encoded) > self.budget:
            raise ExtractionLimit(
                f"Extracted text exceeds {self.budget:,} bytes; original retained."
            )
        self.file.write(clean)
        self.written += len(encoded)

    def close(self):
        self.file.close()


def _text_encoding(path: Path) -> str:
    with path.open("rb") as src:
        bom = src.read(4)
    return "utf-16" if bom.startswith((b"\\xff\\xfe", b"\\xfe\\xff")) else "utf-8-sig"


def _read_text(path: Path, sink: _Sink, replace_errors: bool = False):
    # Use strict decoding first. Any fallback replacement is explicitly
    # reported in the manifest; the original remains byte-for-byte intact.
    with path.open("r", encoding=_text_encoding(path),
                   errors="replace" if replace_errors else "strict", newline="") as src:
        for line in src:
            sink.write(line)


def _read_xlsx(path: Path, sink: _Sink):
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        for sheet in wb:
            sink.write(f"\n# Worksheet: {sheet.title}\n")
            for rownum, row in enumerate(sheet.iter_rows(values_only=True), 1):
                values = [
                    f"{i + 1}={str(value).replace(chr(10), ' ')}"
                    for i, value in enumerate(row) if value is not None
                ]
                sink.write(f"Row {rownum}: " + " | ".join(values) + "\n")
    finally:
        wb.close()


def _read_pdf(path: Path, sink: _Sink):
    from PyPDF2 import PdfReader
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF needs a decrypted copy")
    for i, page in enumerate(reader.pages, 1):
        sink.write(f"\n# Page {i}\n")
        sink.write((page.extract_text() or "[No selectable text on this page]") + "\n")


def _read_docx(path: Path, sink: _Sink):
    from docx import Document
    document = Document(str(path))
    for p in document.paragraphs:
        sink.write(p.text + "\n")
    for i, table in enumerate(document.tables, 1):
        sink.write(f"\n# Table {i}\n")
        for row in table.rows:
            sink.write(" | ".join(cell.text.replace("\n", " ") for cell in row.cells) + "\n")


def _read_pptx(path: Path, sink: _Sink):
    from pptx import Presentation
    slides = Presentation(str(path))
    for i, slide in enumerate(slides.slides, 1):
        sink.write(f"\n# Slide {i}\n")
        for shape in slide.shapes:
            if shape.has_text_frame:
                sink.write(shape.text + "\n")
            if shape.has_table:
                for row in shape.table.rows:
                    sink.write(" | ".join(cell.text for cell in row.cells) + "\n")


def _read_zip(path: Path, sink: _Sink):
    # Inventory only. ZIP members can be arbitrarily large, binary, encrypted,
    # or attacker-controlled; the agent can inspect selected files with tools.
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            sink.write(json.dumps({
                "path": member.filename,
                "bytes": member.file_size,
                "compressed_bytes": member.compress_size,
                "directory": member.is_dir(),
                "encrypted": bool(member.flag_bits & 1),
            }, ensure_ascii=False) + "\n")


def extract_attachment(path: Path, content_type: str, budget: int = MAX_EXTRACTED_BYTES) -> dict:
    """Materialize extracted text by streaming; disclose incomplete or unsupported files."""
    sidecar = path.parent / "extracted.txt"
    suffix = path.suffix.lower()
    kind = "binary"
    handler = None
    if suffix in {".xlsx", ".xlsm"}:
        kind, handler = "spreadsheet", _read_xlsx
    elif suffix == ".pdf" or content_type == "application/pdf":
        kind, handler = "pdf", _read_pdf
    elif suffix == ".docx":
        kind, handler = "document", _read_docx
    elif suffix == ".pptx":
        kind, handler = "presentation", _read_pptx
    elif suffix == ".zip":
        kind, handler = "archive_inventory", _read_zip
    elif suffix in {".csv", ".tsv", ".txt", ".md", ".json", ".jsonl",
                    ".py", ".js", ".ts", ".tsx", ".jsx", ".xml", ".html", ".yaml",
                    ".yml", ".log", ".sql", ".ini", ".toml", ".css"} or content_type.startswith("text/"):
        kind, handler = "text", _read_text

    if not handler:
        return {"kind": kind, "complete": False,
                "note": "No built-in text extractor for this format; original saved for tool inspection.",
                "extracted_path": None}

    sink = _Sink(sidecar, budget)
    complete = True
    note = ("Archive inventory only; member contents are not extracted. "
            "Use a selected archive-member inspection tool or run_python to read files."
            if kind == "archive_inventory" else "")
    try:
        handler(path, sink)
    except UnicodeDecodeError:
        complete = False
        note = ("Some bytes could not be decoded as Unicode and were replaced "
                "in the extracted view. Original bytes are retained for exact analysis.")
        sink.file.seek(0)
        sink.file.truncate(0)
        sink.written = 0
        try:
            _read_text(path, sink, replace_errors=True)
        except Exception as exc:
            note += f" Fallback extraction error: {exc}"
    except Exception as exc:
        complete = False
        note = f"{type(exc).__name__}: {exc}. Original retained for direct analysis."
    finally:
        sink.close()
    return {
        "kind": kind, "complete": complete, "note": note,
        "extracted_path": str(sidecar) if sidecar.exists() else None,
        "extracted_bytes": sink.written,
    }

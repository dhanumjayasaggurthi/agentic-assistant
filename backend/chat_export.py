"""Conversation exports: preserve source and present Markdown structure.

Browser print is the visual-fidelity PDF path (rendered SVG/charts/images).
API exports preserve full textual content, including fenced source, rather than
silently replacing code blocks with placeholder text.
"""
import io
import re
from pathlib import Path

from fpdf import FPDF
from docx import Document
from docx.shared import Pt

_FONTS = [
    (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
     Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
]


def _font_paths():
    for regular, bold in _FONTS:
        if regular.is_file() and bold.is_file():
            return regular, bold
    raise RuntimeError(
        "Unicode PDF font unavailable. Install Arial/DejaVu Sans, or use browser Print > Save as PDF."
    )


def _lines(text):
    """Only normalize newlines. Never discard fences, diagrams, URLs or data."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def export_pdf(title: str, messages: list) -> io.BytesIO:
    font, bold = _font_paths()
    pdf = FPDF()
    pdf.set_margins(17, 18, 17)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("RDI", "", str(font))
    pdf.add_font("RDI", "B", str(bold))
    pdf.add_page()
    pdf.set_font("RDI", "B", 16)
    pdf.multi_cell(0, 9, title, wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    for item in messages:
        role = (item.get("role") or "assistant").upper()
        pdf.set_font("RDI", "B", 10)
        pdf.set_text_color(100, 60, 65) if role == "USER" else pdf.set_text_color(55, 60, 120)
        pdf.multi_cell(0, 7, role, wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 30, 30)
        in_code = False
        for line in _lines(item.get("content") or ""):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code = not in_code
                pdf.set_font("RDI", "", 8)
                pdf.multi_cell(0, 5, line, wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
                continue
            if in_code:
                pdf.set_font("RDI", "", 8)
                pdf.multi_cell(0, 5, line or " ", wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
            elif stripped.startswith("#"):
                depth = len(stripped) - len(stripped.lstrip("#"))
                if depth <= 6 and stripped[depth:depth + 1] == " ":
                    pdf.set_font("RDI", "B", max(10, 15 - depth))
                    pdf.multi_cell(0, 7, stripped[depth + 1:], wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
                else:
                    pdf.set_font("RDI", "", 10)
                    pdf.multi_cell(0, 6, line or " ", wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.set_font("RDI", "", 10)
                pdf.multi_cell(0, 6, line or " ", wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    buf = io.BytesIO(pdf.output())
    buf.seek(0)
    return buf


def export_docx(title: str, messages: list) -> io.BytesIO:
    doc = Document()
    doc.add_heading(title, 0)
    for item in messages:
        doc.add_heading((item.get("role") or "assistant").upper(), level=2)
        lines = _lines(item.get("content") or "")
        i, in_code = 0, False
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code = not in_code
                paragraph = doc.add_paragraph(line)
                paragraph.style = "No Spacing"
                for run in paragraph.runs:
                    run.font.name = "Consolas"
                    run.font.size = Pt(9)
            elif in_code:
                paragraph = doc.add_paragraph(line)
                paragraph.style = "No Spacing"
                for run in paragraph.runs:
                    run.font.name = "Consolas"
                    run.font.size = Pt(9)
            elif re.fullmatch(r"\s*\|?[\s:\-|]+\|?\s*", stripped) and "|" in stripped:
                # Table separator row is formatting, not user content.
                doc.add_paragraph(line)
            elif re.match(r"^#{1,6}\s+", stripped):
                match = re.match(r"^(#{1,6})\s+(.*)", stripped)
                doc.add_heading(match.group(2), level=min(len(match.group(1)), 4))
            elif re.match(r"^\s*[-*+]\s+", line):
                doc.add_paragraph(re.sub(r"^\s*[-*+]\s+", "", line), style="List Bullet")
            elif re.match(r"^\s*\d+[.)]\s+", line):
                doc.add_paragraph(re.sub(r"^\s*\d+[.)]\s+", "", line), style="List Number")
            else:
                doc.add_paragraph(line)
            i += 1
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

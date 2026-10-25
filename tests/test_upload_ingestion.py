"""Regression coverage for XLSX NUL, long CSV, uploaded binary isolation,
complete context access, and multi-page read-only analysis."""
import asyncio
import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from openpyxl import Workbook
from starlette.datastructures import Headers, UploadFile

from backend.attachment_processing import extract_attachment
from backend.agents.tools import _file_overview, _read_file, _workspace_var
from backend.agents.chat_agent import trim_history
from backend.main import upload_file


class AttachmentProcessingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.context = _workspace_var.set(self.path)

    def tearDown(self):
        _workspace_var.reset(self.context)
        self.temp.cleanup()

    async def test_actual_xlsx_binary_upload_never_sent_as_text(self):
        book = Workbook()
        ws = book.active
        ws.title = "Sites"
        ws.append(["Site Name", "Count"])
        for i in range(1500):
            ws.append([f"Site {i}", i])
        blob = io.BytesIO()
        book.save(blob)
        payload = blob.getvalue()
        # .xlsx is ZIP-backed binary, not valid UTF-8 text.
        self.assertEqual(payload[:2], b"PK")
        file = UploadFile(
            filename="sites_detected_as_php.xlsx", file=io.BytesIO(payload),
            headers=Headers({"content-type":
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
        )
        with (
            patch("backend.main._user_ws_base", return_value=self.path),
            patch("backend.main.get_config", return_value=SimpleNamespace(max_upload_mb=20)),
            patch("backend.database.save_attachment", new_callable=AsyncMock) as save,
        ):
            reply = await upload_file(file, conversation_id=None, user={"id": "demo"})
        self.assertEqual(reply["extraction"]["kind"], "spreadsheet")
        self.assertTrue(reply["extraction"]["complete"])
        self.assertEqual(save.await_args.args[3], "")  # Never store binary bytes in TEXT.
        kwargs = save.await_args.kwargs
        original = self.path / kwargs["storage_path"]
        extracted = original.parent / "extracted.txt"
        self.assertEqual(original.read_bytes(), payload)
        txt = extracted.read_text(encoding="utf-8")
        self.assertNotIn("\x00", txt)
        self.assertIn("Row 1501:", txt)
        self.assertIn("Site 1499", txt)
        # Materialized paths have exact line-range, citation-friendly semantics.
        report = _file_overview({"path": kwargs["storage_path"]})
        self.assertIn('"rows": 1500', report)
        self.assertIn('"sheet": "Sites"', report)

    async def test_csv_larger_than_previous_20000_character_limit(self):
        path = self.path / "study.csv"
        with path.open("w", encoding="utf-8", newline="") as dest:
            writer = csv.writer(dest)
            writer.writerow(["id", "name", "value"])
            for i in range(10000):
                writer.writerow([i, "Record " + str(i), i * 2])
        meta = extract_attachment(path, "text/csv")
        self.assertTrue(meta["complete"])
        full = (self.path / "extracted.txt").read_text(encoding="utf-8")
        self.assertGreater(len(full), 20000)
        self.assertIn("9999,Record 9999,19998", full)
        overview = _file_overview({"path": "study.csv"})
        self.assertIn('"rows": 10000', overview)
        chunk = await _read_file({"path": "extracted.txt",
                                   "start_line": 1, "end_line": 12, "max_chars": 12000})
        self.assertIn("NEXT_START_LINE=13", chunk)
        tail = await _read_file({"path": "extracted.txt",
                                  "start_line": 10001, "end_line": 10001})
        self.assertIn("9999,Record 9999,19998", tail)
        self.assertIn("END_OF_FILE", tail)

    async def test_single_oversized_row_has_cursor_and_no_content_loss(self):
        path = self.path / "longline.txt"
        payload = "ABCDEFGHIJ" * 5000
        path.write_text(payload + "\n", encoding="utf-8")
        cursor = 0
        recovered = []
        for _ in range(8):
            result = await _read_file({"path": "longline.txt",
                "start_line": 1, "end_line": 1,
                "start_char": cursor, "max_chars": 8000})
            part = result.split("\n[1] ", 1)[1].split("\n", 1)[0]
            recovered.append(part)
            if "NEXT_START_CHAR=" not in result:
                break
            cursor = int(result.split("NEXT_START_CHAR=", 1)[1].split()[0])
        self.assertEqual("".join(recovered), payload)
        self.assertIn("END_OF_FILE", result)

    async def test_utf16_source_recognized_and_preserved(self):
        path = self.path / "utf16.csv"
        path.write_bytes("name,value\nAlpha,42\n".encode("utf-16"))
        report = extract_attachment(path, "text/csv")
        self.assertTrue(report["complete"])
        self.assertEqual((self.path / "extracted.txt").read_text(), "name,value\nAlpha,42\n")

    async def test_zip_inventory_no_unsafe_member_extraction(self):
        archive = self.path / "research.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../../unexpected.txt", "untrusted content")
            zf.writestr("docs/readme.md", "# Research")
        report = extract_attachment(archive, "application/zip")
        self.assertTrue(report["complete"])
        listing = (self.path / "extracted.txt").read_text(encoding="utf-8")
        self.assertIn("../../unexpected.txt", listing)
        self.assertIn("docs/readme.md", listing)
        self.assertFalse((self.path.parent / "unexpected.txt").exists())

    async def test_legacy_nul_text_is_not_misrepresented(self):
        item = self.path / "legacy.txt"
        item.write_bytes(b"before\x00after\nend\n")
        meta = extract_attachment(item, "text/plain")
        self.assertTrue(meta["complete"])
        text = (self.path / "extracted.txt").read_text()
        self.assertIn("before\ufffdafter", text)
        self.assertNotIn("\x00", text)

    async def test_large_context_is_preserved_for_pagination(self):
        history = [{"role": "user", "content": "x" * 190_000}]
        self.assertIs(trim_history(history), history)

    async def test_extraction_limit_is_explicit_and_original_is_preserved(self):
        sample = self.path / "big.txt"
        sample.write_text("A" * 2500, encoding="utf-8")
        meta = extract_attachment(sample, "text/plain", budget=1024)
        self.assertFalse(meta["complete"])
        self.assertIn("Original retained", meta["note"])
        self.assertEqual(len(sample.read_text()), 2500)


if __name__ == "__main__":
    unittest.main()

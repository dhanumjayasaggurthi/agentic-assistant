import unittest

from backend.ws_handler import _normalize_attachments, _should_auto_agent


class AutoAgentJourneyTests(unittest.TestCase):
    def test_fix_code_promotes_to_agent(self):
        self.assertTrue(_should_auto_agent("Fix this code and run tests", []))

    def test_create_powerpoint_promotes_to_agent(self):
        self.assertTrue(_should_auto_agent("Build a PowerPoint for this analysis", []))

    def test_plain_explanation_stays_chat(self):
        self.assertFalse(_should_auto_agent("Explain what retrieval augmented generation means", []))

    def test_attachment_analysis_promotes(self):
        atts = [{"attachment_id": "a1", "name": "sample.py", "type": "text/plain"}]
        self.assertTrue(_should_auto_agent("Analyze the attached file and fix it", atts))


class AttachmentJourneyTests(unittest.TestCase):
    def test_handle_shape_survives_client_to_server_normalization(self):
        normalized = _normalize_attachments([{
            "id": "abc",
            "name": "trial.py",
            "content_type": "text/x-python",
            "size": 1234,
        }])
        self.assertEqual(normalized, [{
            "name": "trial.py",
            "type": "text/x-python",
            "content_type": "text/x-python",
            "id": "abc",
            "attachment_id": "abc",
            "size": 1234,
        }])

    def test_legacy_inline_attachment_still_supported(self):
        normalized = _normalize_attachments([{
            "name": "old.txt",
            "type": "text/plain",
            "content": "legacy",
        }])
        self.assertEqual(normalized[0]["content"], "legacy")


if __name__ == "__main__":
    unittest.main()

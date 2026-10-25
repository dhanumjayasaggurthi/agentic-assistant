"""Regression guard for PostgreSQL upgrades from older attachment schemas."""
import unittest

from backend.database import _MIGRATIONS, _SCHEMA


class DatabaseSchemaMigrationTests(unittest.TestCase):
    def test_attachment_user_index_is_created_after_column_migration(self):
        add_column = "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS user_id TEXT"
        create_index = (
            "CREATE INDEX IF NOT EXISTS idx_attachments_user "
            "ON attachments (user_id, created_at DESC)"
        )
        self.assertNotIn("idx_attachments_user", _SCHEMA)
        self.assertIn(add_column, _MIGRATIONS)
        self.assertIn(create_index, _MIGRATIONS)
        self.assertLess(_MIGRATIONS.index(add_column), _MIGRATIONS.index(create_index))


if __name__ == "__main__":
    unittest.main()

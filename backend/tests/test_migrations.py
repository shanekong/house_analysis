from __future__ import annotations

import io
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config


class MigrationCompatibilityTest(unittest.TestCase):
    def test_mysql_offline_migration_compiles(self) -> None:
        backend_dir = Path(__file__).resolve().parents[1]
        output = io.StringIO()
        config = Config(str(backend_dir / "alembic.ini"), output_buffer=output)
        config.set_main_option("script_location", str(backend_dir / "migrations"))
        config.set_main_option("sqlalchemy.url", "mysql+pymysql://user:password@localhost/house_analysis")
        command.upgrade(config, "head", sql=True)
        sql = output.getvalue()
        self.assertIn("CREATE TABLE market_observation", sql)
        self.assertIn("ALTER TABLE data_source ADD COLUMN license_name", sql)


if __name__ == "__main__":
    unittest.main()

"""A blank Neo4j password is a configuration error, not a default login."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from naive_rag.config import PROJECT_ROOT, Settings
from naive_rag.graph import GraphUnavailable, get_driver


class Neo4jPasswordRequiredTest(unittest.TestCase):
    def test_settings_have_no_password_without_env(self) -> None:
        settings = Settings(_env_file=None, neo4j_password=None)
        self.assertFalse(str(settings.neo4j_password or "").strip())

    def test_get_driver_stops_before_connect_when_password_missing(self) -> None:
        get_driver.cache_clear()
        settings = Settings(_env_file=None, neo4j_password=None)
        with patch("naive_rag.graph.get_settings", return_value=settings):
            with patch("naive_rag.graph.GraphDatabase.driver") as driver:
                with self.assertRaises(GraphUnavailable) as caught:
                    get_driver()
        driver.assert_not_called()
        self.assertIn("neo4j_password", str(caught.exception))

    def test_versioned_files_have_no_password_fallback(self) -> None:
        example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
        config = Path(PROJECT_ROOT / "src" / "naive_rag" / "config.py").read_text(
            encoding="utf-8")
        password_line = next(
            line for line in example.splitlines() if line.startswith("NEO4J_PASSWORD=")
        )
        self.assertEqual(password_line, "NEO4J_PASSWORD=")
        self.assertIn("NEO4J_PASSWORD:?", compose)
        self.assertNotIn("NEO4J_PASSWORD:-", compose)
        self.assertIn("neo4j_password: str | None = None", config)


if __name__ == "__main__":
    unittest.main()

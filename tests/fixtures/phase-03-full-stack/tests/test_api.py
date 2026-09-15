import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol, cast


class AcceptanceApi(Protocol):
    DATABASE: Path

    def validate_title(self, value: object) -> str: ...

    def connect(self) -> AbstractContextManager[sqlite3.Connection]: ...


path = Path(__file__).resolve().parents[1] / "api" / "app.py"
spec = importlib.util.spec_from_file_location("phase_03_acceptance_api", path)
if spec is None or spec.loader is None:
    raise RuntimeError("acceptance API fixture could not be loaded")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app = cast(AcceptanceApi, module)


class ApiTests(unittest.TestCase):
    def test_title_validation(self) -> None:
        self.assertEqual(app.validate_title(" Useful "), "Useful")
        with self.assertRaisesRegex(ValueError, "required"):
            app.validate_title(" ")
        with self.assertRaisesRegex(ValueError, "80"):
            app.validate_title("x" * 81)

    def test_state_persists_across_connections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = app.DATABASE
            app.DATABASE = Path(directory) / "state.sqlite3"
            try:
                with app.connect() as database:
                    database.execute("INSERT INTO items(title) VALUES ('Persisted')")
                with app.connect() as database:
                    self.assertEqual(
                        database.execute("SELECT title FROM items").fetchone()[0], "Persisted"
                    )
            finally:
                app.DATABASE = original


if __name__ == "__main__":
    unittest.main()

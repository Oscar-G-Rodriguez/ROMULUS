import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from import_user_market_data import run_import  # noqa: E402
from providers.provider_utils import write_fetch_provenance  # noqa: E402
from universe_utils import (  # noqa: E402
    add_ticker,
    ensure_universe_file,
    read_universe,
    remove_ticker,
    write_universe,
)


class UniverseUtilsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        Path("data/import").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_universe_read_write(self) -> None:
        write_universe(["aapl", "MSFT"])
        symbols = read_universe(Path("data/import/universe.csv"))
        self.assertEqual(symbols, ["AAPL", "MSFT"])

        symbols = add_ticker("NVDA")
        self.assertIn("NVDA", symbols)

        symbols = remove_ticker("MSFT")
        self.assertNotIn("MSFT", symbols)

    def test_ensure_universe_file(self) -> None:
        symbols = ensure_universe_file()
        self.assertGreater(len(symbols), 0)
        self.assertTrue(Path("data/import/universe.csv").exists())


class FetchProvenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        Path("artifacts").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_fetch_provenance_creation(self) -> None:
        path = write_fetch_provenance(
            run_id="test-run",
            provider="stooq",
            symbols=["AAPL"],
            date_start="2020-01-01",
            date_end="2020-01-31",
            per_ticker_status={"AAPL": {"status": "ok", "rows": "21"}},
            sources=["[SOURCE_PLACEHOLDER | LOCATION-TODO | test]"],
            notes="test",
        )
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["fetch_run_id"], "test-run")
        self.assertEqual(data["provider"], "stooq")


class IngestLinksFetchRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        Path("data/import").mkdir(parents=True, exist_ok=True)
        os.environ["ROMULUS_DB_PATH"] = str(Path("data/romulus.db"))

        write_universe(["AAPL"])
        sample_path = Path("data/import/sample.csv")
        sample_path.write_text(
            "symbol,date,open,high,low,close,volume\n"
            "AAPL,2020-01-02,1,2,0.5,1.5,1000\n",
            encoding="ascii",
        )

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        os.environ.pop("ROMULUS_DB_PATH", None)
        self._tmp.cleanup()

    def test_ingest_links_fetch_run(self) -> None:
        result = run_import(
            vendor="test_vendor",
            dataset_id="test_dataset",
            fetch_run_ids=["fetch-123"],
        )
        self.assertEqual(result.get("code"), 0)

        conn = sqlite3.connect("data/romulus.db")
        row = conn.execute(
            "SELECT fetch_run_ids FROM ingestion_provenance LIMIT 1"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertIn("fetch-123", row[0])


class ApiEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        Path("data/import").mkdir(parents=True, exist_ok=True)
        os.environ["ROMULUS_DB_PATH"] = str(Path("data/romulus.db"))

        write_universe(["AAPL"])
        sample_path = Path("data/import/sample.csv")
        sample_path.write_text(
            "symbol,date,open,high,low,close,volume\n"
            "AAPL,2020-01-02,1,2,0.5,1.5,1000\n",
            encoding="ascii",
        )

        sys.path.insert(0, str(ROOT_DIR))
        from backend.app.main import app
        from fastapi.testclient import TestClient

        self.client = TestClient(app)
        token = self.client.post(
            "/api/auth/register",
            json={"email": "test@example.com", "password": "pass"},
        ).json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        os.environ.pop("ROMULUS_DB_PATH", None)
        self._tmp.cleanup()

    def test_data_endpoints(self) -> None:
        resp = self.client.get("/api/data/tickers", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("AAPL", resp.json().get("symbols", []))

        ingest_resp = self.client.post(
            "/api/data/ingest",
            headers=self.headers,
            json={"vendor": "test", "dataset_id": "test", "fetch_run_ids": ["fetch-1"]},
        )
        self.assertEqual(ingest_resp.status_code, 200)
        run_id = ingest_resp.json().get("run_id")
        self.assertTrue(run_id)

        last_resp = self.client.get("/api/data/last-ingestion", headers=self.headers)
        self.assertEqual(last_resp.status_code, 200)
        payload = last_resp.json()
        self.assertEqual(payload.get("run_id"), run_id)
        self.assertTrue(payload.get("report_path"))
        self.assertTrue(payload.get("provenance_ref"))


if __name__ == "__main__":
    unittest.main()

"""Offline checks for the production Atlas import's read-only verification mode."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from scripts import import_atlas_sales as script


TABLES = (
    "sales_companies",
    "sales_contacts",
    "sales_opportunities",
    "sales_activities",
    "sales_leads",
    "sales_files",
)


class FakeSession:
    def __init__(self, *, fail_on=None):
        self.events = []
        self.fail_on = fail_on
        self.counts = dict(zip(TABLES, (9123, 9920, 1635, 11318, 2500, 6029)))
        self.commit = AsyncMock(side_effect=AssertionError("writes are forbidden"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.events.append("closed")

    async def execute(self, statement):
        sql = str(statement)
        self.events.append(sql)
        if self.fail_on == len(self.events):
            raise RuntimeError("SYNTHETIC_PRIVATE_MARKER")
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(one=lambda: self.counts)
        )

    async def rollback(self):
        self.events.append("rollback")


class AtlasCountsCliTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        database = ModuleType("app.core.database")
        database.AsyncSessionLocal = lambda: self.session
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {"app.core.database": database}).start()
        patch.dict(os.environ, {}, clear=True).start()
        self.import_main = patch.object(
            script, "_main", new=AsyncMock(side_effect=AssertionError("no import"))
        ).start()
        self.source_connect = patch.object(
            script.asyncpg,
            "connect",
            new=AsyncMock(side_effect=AssertionError("no Atlas connection")),
        ).start()
        self.files = patch.object(
            script, "_copy_files", new=AsyncMock(side_effect=AssertionError("no files"))
        ).start()
        self.output = io.StringIO()
        self.error = io.StringIO()

    def lock(self):
        path = Path(f"/tmp/nexus-atlas-import-{uuid.uuid4().int}")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def run_cli(self, arguments):
        with (
            contextlib.redirect_stdout(self.output),
            contextlib.redirect_stderr(self.error),
        ):
            return script.main(arguments)

    def test_counts_need_no_atlas_secrets_and_use_one_consistent_read_only_snapshot(
        self,
    ):
        self.assertEqual(self.run_cli(["--counts-only"]), 0)
        self.assertEqual(
            json.loads(self.output.getvalue()),
            {
                "applied": False,
                "mode": "counts-only",
                "counts": self.session.counts,
            },
        )
        readonly, select, rollback, closed = self.session.events
        self.assertEqual(
            readonly, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
        self.assertEqual(re.findall(r"FROM\s+(\w+)", select, re.I), list(TABLES))
        self.assertEqual(len(re.findall(r"count\(\*\)", select, re.I)), 6)
        self.assertTrue(select.startswith("SELECT "))
        self.assertEqual((rollback, closed), ("rollback", "closed"))
        self.session.commit.assert_not_awaited()
        self.import_main.assert_not_called()
        self.source_connect.assert_not_called()
        self.files.assert_not_called()

    def test_counts_lock_runs_once_and_second_tick_reads_nothing(self):
        lock = self.lock()
        self.assertEqual(self.run_cli(["--counts-only", "--lock", str(lock)]), 0)
        events = list(self.session.events)
        self.assertEqual(self.run_cli(["--counts-only", "--lock", str(lock)]), 3)
        self.assertEqual(self.session.events, events)
        self.assertIn("already ran", self.error.getvalue())
        self.source_connect.assert_not_called()

    def test_apply_and_files_conflicts_fail_before_lock_or_database_access(self):
        for flags in (["--apply"], ["--files"], ["--apply", "--files"]):
            with self.subTest(flags=flags):
                lock = self.lock()
                with self.assertRaises(SystemExit) as caught:
                    self.run_cli(["--counts-only", *flags, "--lock", str(lock)])
                self.assertEqual(caught.exception.code, 2)
                self.assertFalse(lock.exists())
        self.assertEqual(self.session.events, [])
        self.import_main.assert_not_called()
        self.source_connect.assert_not_called()

    def test_failure_rolls_back_and_public_locked_output_contains_only_error_type(self):
        self.session.fail_on = 2
        lock = self.lock()
        self.assertEqual(self.run_cli(["--counts-only", "--lock", str(lock)]), 1)
        self.assertEqual(
            json.loads(self.output.getvalue()),
            {
                "applied": False,
                "error": "RuntimeError",
            },
        )
        public = self.output.getvalue() + self.error.getvalue()
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", public)
        self.assertNotIn("Traceback", public)
        self.assertIn("SYNTHETIC_PRIVATE_MARKER", (lock / "error.log").read_text())
        self.assertEqual(self.session.events[-2:], ["rollback", "closed"])
        self.session.commit.assert_not_awaited()
        self.source_connect.assert_not_called()

    def test_read_only_setup_failure_does_not_run_counts_and_still_rolls_back(self):
        self.session.fail_on = 1
        lock = self.lock()
        self.assertEqual(self.run_cli(["--counts-only", "--lock", str(lock)]), 1)
        self.assertEqual(len(self.session.events), 3)
        self.assertEqual(self.session.events[-2:], ["rollback", "closed"])
        self.session.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

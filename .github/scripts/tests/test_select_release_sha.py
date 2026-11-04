import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "select_release_sha", ROOT / ".github/scripts/select_release_sha.py"
)
SELECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECT)

A, B, C = ("a" * 40, "b" * 40, "c" * 40)


def run(status, conclusion=None, sha=A):
    return {"head_sha": sha, "status": status, "conclusion": conclusion, "created_at": "x"}


class SelectTests(unittest.TestCase):
    def test_green_head_is_released(self):
        selection = SELECT.select_release(B, A, {B: "success"}.__getitem__, target_is_verified=True)
        self.assertEqual((selection.release_sha, selection.defer), (B, False))

    def test_head_equal_to_verified_target_needs_no_lookup(self):
        def status_of(sha):
            raise AssertionError("no lookup expected")

        selection = SELECT.select_release(A, A, status_of, target_is_verified=True)
        self.assertEqual(selection.release_sha, A)

    def test_red_or_pending_head_defers_instead_of_riding_along(self):
        for status in ("failure", "in_progress", "missing"):
            with self.subTest(status=status):
                selection = SELECT.select_release(
                    B, A, {B: status}.__getitem__, target_is_verified=True
                )
                self.assertEqual((selection.release_sha, selection.defer), ("", True))

    def test_manual_dispatch_checks_head_even_when_it_is_the_target(self):
        selection = SELECT.select_release(A, A, {A: "failure"}.__getitem__, target_is_verified=False)
        self.assertTrue(selection.defer)


class AcceptTests(unittest.TestCase):
    def accept(self, live, rel, statuses, wait=60.0):
        seq = list(statuses)
        clock = [0.0]

        def status_of(sha):
            return seq.pop(0) if len(seq) > 1 else seq[0]

        def sleep(seconds):
            clock[0] += seconds

        return SELECT.accept_live(
            live, A, lambda base, head: rel, status_of,
            wait_seconds=wait, poll_seconds=20, sleep=sleep, clock=lambda: clock[0],
        )

    def test_equal_version_is_accepted(self):
        self.assertEqual(self.accept(A, "identical", ["failure"]).code, 0)

    def test_green_descendant_is_accepted_after_waiting_for_its_gate(self):
        self.assertEqual(self.accept(B, "ahead", ["in_progress", "in_progress", "success"]).code, 0)

    def test_red_descendant_is_a_hard_failure(self):
        self.assertEqual(self.accept(B, "ahead", ["failure"]).code, 1)

    def test_descendant_whose_gate_never_finishes_is_a_failure(self):
        result = self.accept(B, "ahead", ["in_progress"], wait=60)
        self.assertEqual((result.code, result.status), (1, "in_progress"))

    def test_stale_or_unrelated_version_is_retried(self):
        self.assertEqual(self.accept(C, "behind", ["success"]).code, 2)
        self.assertEqual(self.accept("unknown", "ahead", ["success"]).code, 2)


class GateStatusTests(unittest.TestCase):
    def test_newest_attempt_wins(self):
        runs = [
            {**run("completed", "failure"), "run_attempt": 1},
            {**run("completed", "success"), "run_attempt": 2},
        ]
        fetch = lambda path: {"workflow_runs": runs}
        self.assertEqual(SELECT.gate_status(fetch, "o/r", A, "main"), "success")

    def test_in_progress_and_foreign_runs(self):
        self.assertEqual(
            SELECT.gate_status(lambda p: {"workflow_runs": [run("in_progress")]}, "o/r", A, "main"),
            "in_progress",
        )
        self.assertEqual(
            SELECT.gate_status(lambda p: {"workflow_runs": [run("completed", "success", B)]}, "o/r", A, "main"),
            "missing",
        )


class FreezeWindowTests(unittest.TestCase):
    """PROD-04: automatyczny deploy nie restartuje produkcji w nocy."""

    def at(self, iso):
        return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)

    def test_window_is_warsaw_local_time_in_summer_and_winter(self):
        # Lato (CEST = UTC+2): 04:30Z = 06:30 lokalnie → w oknie 0-7.
        self.assertTrue(SELECT.in_freeze(self.at("2026-07-01T04:30:00"), "0-7"))
        # 05:15Z = 07:15 lokalnie → po oknie (poranny schedule wdraża).
        self.assertFalse(SELECT.in_freeze(self.at("2026-07-01T05:15:00"), "0-7"))
        # Zima (CET = UTC+1): 05:15Z = 06:15 lokalnie → nadal w oknie.
        self.assertTrue(SELECT.in_freeze(self.at("2026-12-01T05:15:00"), "0-7"))
        self.assertFalse(SELECT.in_freeze(self.at("2026-12-01T06:15:00"), "0-7"))
        # 22:30Z w lecie = 00:30 lokalnie → w oknie mimo „wczoraj” w UTC.
        self.assertTrue(SELECT.in_freeze(self.at("2026-07-01T22:30:00"), "0-7"))

    def test_day_window_matches_the_evening_cron_slots(self):
        # Okno 8-18 (decyzja 14.10.2026, godziny od 22.10.2026): wdrożenia
        # tylko 18:00–08:00. Lato: 16:23Z = 18:23 lokalnie → wolno; zima:
        # 16:23Z = 17:23 → jeszcze okno, wdraża slot 17:23Z (= 18:23 zimą).
        self.assertFalse(SELECT.in_freeze(self.at("2026-07-01T16:23:00"), "8-18"))
        self.assertTrue(SELECT.in_freeze(self.at("2026-12-01T16:23:00"), "8-18"))
        self.assertFalse(SELECT.in_freeze(self.at("2026-12-01T17:23:00"), "8-18"))
        # Zapasowy slot 04:23Z: 06:23 latem, 05:23 zimą — oba przed 08:00.
        self.assertFalse(SELECT.in_freeze(self.at("2026-07-01T04:23:00"), "8-18"))
        self.assertFalse(SELECT.in_freeze(self.at("2026-12-01T04:23:00"), "8-18"))
        # Spóźniony cron po 08:00 trafia już w okno.
        self.assertTrue(SELECT.in_freeze(self.at("2026-07-01T06:30:00"), "8-18"))
        self.assertTrue(SELECT.in_freeze(self.at("2026-07-01T12:00:00"), "8-18"))

    def test_window_across_midnight_and_off_values(self):
        self.assertTrue(SELECT.in_freeze(self.at("2026-12-01T22:30:00"), "22-6"))
        self.assertFalse(SELECT.in_freeze(self.at("2026-12-01T12:00:00"), "22-6"))
        for off in ("", "off", "none", "0"):
            self.assertFalse(SELECT.in_freeze(self.at("2026-07-01T00:30:00"), off))
        for bad in ("7", "0-25", "5-5", "noc"):
            with self.assertRaises(ValueError):
                SELECT.parse_freeze_window(bad)

    def test_weekend_has_no_window(self):
        # Doprecyzowanie Artura 17.10.2026: okno 8-18 tylko pon–pt, w sobotę
        # i niedzielę wdrażamy o każdej porze. Październik 2026 = CEST (UTC+2).
        # Sobota 17.10 11:00 w Warszawie → bez okna; piątek 16.10 11:00 → okno.
        self.assertFalse(SELECT.in_freeze(self.at("2026-10-17T09:00:00"), "8-18"))
        self.assertFalse(SELECT.in_freeze(self.at("2026-10-18T09:00:00"), "8-18"))
        self.assertTrue(SELECT.in_freeze(self.at("2026-10-16T09:00:00"), "8-18"))
        # Poniedziałek 19.10: 07:59 jeszcze bez okna, od 08:00 okno.
        self.assertFalse(SELECT.in_freeze(self.at("2026-10-19T05:59:00"), "8-18"))
        self.assertTrue(SELECT.in_freeze(self.at("2026-10-19T06:00:00"), "8-18"))
        # Zima (CET): sobota 05.12 12:00 → bez okna.
        self.assertFalse(SELECT.in_freeze(self.at("2026-12-05T11:00:00"), "8-18"))

    def test_weekend_counts_by_the_local_date_of_now(self):
        # Okno przez północ: niedziela 23:30 → weekend; piątek 23:30 → okno;
        # sobota 00:30 (w UTC jeszcze piątek) → weekend.
        self.assertFalse(SELECT.in_freeze(self.at("2026-10-18T21:30:00"), "22-6"))
        self.assertTrue(SELECT.in_freeze(self.at("2026-10-16T21:30:00"), "22-6"))
        self.assertFalse(SELECT.in_freeze(self.at("2026-10-16T22:30:00"), "22-6"))
        # Poniedziałek 00:30 (w UTC jeszcze niedziela) → okno.
        self.assertTrue(SELECT.in_freeze(self.at("2026-10-18T22:30:00"), "22-6"))
        self.assertTrue(SELECT.in_freeze(self.at("2026-10-18T22:30:00"), "0-7"))

    def test_window_start_after_a_weekend_is_monday_midnight(self):
        # Okno 22-6 w poniedziałek 03:00 zaczęło się o północy, nie w niedzielę
        # o 22:00 — niedzielny wieczór był bez okna.
        start = SELECT.window_closed_at(self.at("2026-10-19T01:00:00"), "22-6")
        self.assertEqual(start, self.at("2026-10-18T22:00:00"))  # 00:00 CEST
        # Wtorek 03:00 → poniedziałek 22:00, jak dotąd.
        start = SELECT.window_closed_at(self.at("2026-10-20T01:00:00"), "22-6")
        self.assertEqual(start, self.at("2026-10-19T20:00:00"))
        start = SELECT.window_closed_at(self.at("2026-10-19T08:00:00"), "8-18")
        self.assertEqual(start, self.at("2026-10-19T06:00:00"))

    def test_in_freeze_cli_exit_codes(self):
        args = SELECT.parse_args(["in-freeze", "--freeze-window", "0-7"])
        night = datetime(2026, 7, 1, 1, 0, tzinfo=timezone.utc)
        day = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(SELECT._run_in_freeze(args, now=night), 0)
        self.assertEqual(SELECT._run_in_freeze(args, now=day), 1)
        bad = SELECT.parse_args(["in-freeze", "--freeze-window", "noc"])
        self.assertEqual(SELECT._run_in_freeze(bad, now=night), 1)

    def test_hold_reason(self):
        self.assertEqual(SELECT.hold_reason("success", None), "")
        self.assertEqual(SELECT.hold_reason("in_progress", 500), "")
        self.assertEqual(SELECT.hold_reason("night_freeze", None), "")
        self.assertEqual(SELECT.hold_reason("missing", 30), "")
        self.assertEqual(SELECT.hold_reason("missing", None), "")
        self.assertIn("od 61 min", SELECT.hold_reason("missing", 61))
        self.assertIn("failure", SELECT.hold_reason("failure", 1))


class CliTests(unittest.TestCase):
    def env(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out, env = Path(tmp.name, "out"), Path(tmp.name, "env")
        old = {k: os.environ.get(k) for k in ("GITHUB_OUTPUT", "GITHUB_ENV")}
        os.environ["GITHUB_OUTPUT"], os.environ["GITHUB_ENV"] = str(out), str(env)

        def restore():
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)
        return out, env

    def test_select_defers_on_pending_head(self):
        out, _ = self.env()

        def fetch(path):
            if path.startswith("repos/o/r/commits/"):
                return {"sha": B}
            return {"workflow_runs": [run("in_progress", sha=B)]}

        self.assertEqual(SELECT.main(["select", "--repo", "o/r", "--target", A], fetch=fetch), 0)
        self.assertIn("defer=true", out.read_text())
        self.assertIn("release_sha=\n", out.read_text())

    def test_manual_select_with_red_head_fails(self):
        self.env()

        def fetch(path):
            if path.startswith("repos/o/r/commits/"):
                return {"sha": A}
            return {"workflow_runs": [run("completed", "failure")]}

        code = SELECT.main(["select", "--repo", "o/r", "--target", A, "--target-unverified"], fetch=fetch)
        self.assertEqual(code, 1)

    def test_frozen_automatic_select_defers_without_touching_the_api(self):
        out, _ = self.env()

        def fetch(path):
            raise AssertionError("w oknie ciszy nie pytamy API")

        args = SELECT.parse_args(
            ["select", "--repo", "o/r", "--target", A, "--freeze-window", "0-7"]
        )
        now = datetime(2026, 7, 1, 1, 0, tzinfo=timezone.utc)  # 03:00 w Warszawie
        self.assertEqual(SELECT._run_select(args, fetch, now=now), 0)
        text = out.read_text()
        self.assertIn("defer=true", text)
        self.assertIn("head_status=night_freeze", text)
        self.assertIn("hold_alert=\n", text)

    def test_manual_dispatch_in_the_window_fails_with_instruction(self):
        # Od 14.10.2026 ręczny „Run workflow” (także z „Coolify set env”)
        # szanuje okno — czerwony bieg mówi, kiedy ponowić. Odroczenie na
        # zielono gubiłoby redeploy po zmianie env: wieczorny bieg pominie
        # wersję, która już stoi na produkcji.
        out, _ = self.env()

        def fetch(path):
            raise AssertionError("w oknie ciszy nie pytamy API")

        args = SELECT.parse_args(
            ["select", "--repo", "o/r", "--target", A, "--target-unverified",
             "--freeze-window", "8-18"]
        )
        now = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)  # 12:00 w Warszawie
        self.assertEqual(SELECT._run_select(args, fetch, now=now), 1)
        text = out.read_text()
        self.assertIn("defer=true", text)
        self.assertIn("head_status=night_freeze", text)

    def test_manual_dispatch_outside_the_window_deploys(self):
        out, _ = self.env()

        def fetch(path):
            if path.startswith("repos/o/r/commits/"):
                return {"sha": A}
            return {"workflow_runs": [run("completed", "success")]}

        args = SELECT.parse_args(
            ["select", "--repo", "o/r", "--target", A, "--target-unverified",
             "--freeze-window", "8-18"]
        )
        now = datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)  # 20:00 w Warszawie
        self.assertEqual(SELECT._run_select(args, fetch, now=now), 0)
        self.assertIn("defer=false", out.read_text())

    def test_saturday_merge_and_manual_dispatch_deploy_at_noon(self):
        # Sobota 17.10.2026 12:00 w Warszawie: bez okna — merge wdraża się od
        # razu, a ręczny „Run workflow” nie potrzebuje emergency.
        now = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)

        def fetch(path):
            if path.startswith("repos/o/r/commits/"):
                return {"sha": A}
            return {"workflow_runs": [run("completed", "success")]}

        for extra in ([], ["--target-unverified"], ["--scheduled"]):
            with self.subTest(extra=extra):
                out, _ = self.env()
                args = SELECT.parse_args(
                    ["select", "--repo", "o/r", "--target", A,
                     "--freeze-window", "8-18", *extra]
                )
                self.assertEqual(SELECT._run_select(args, fetch, now=now), 0)
                text = out.read_text()
                self.assertIn("defer=false", text)
                self.assertNotIn("night_freeze", text)

    def test_emergency_dispatch_ignores_the_window(self):
        out, _ = self.env()

        def fetch(path):
            if path.startswith("repos/o/r/commits/"):
                return {"sha": A}
            return {"workflow_runs": [run("completed", "success")]}

        args = SELECT.parse_args(
            ["select", "--repo", "o/r", "--target", A, "--target-unverified",
             "--freeze-window", "8-18", "--emergency", "--reason", "logowanie nie działa"]
        )
        now = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(SELECT._run_select(args, fetch, now=now), 0)
        self.assertIn("defer=false", out.read_text())

    def test_emergency_needs_a_reason_and_a_manual_dispatch(self):
        self.env()

        def fetch(path):
            raise AssertionError("bez powodu nie ruszamy")

        now = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        for extra in (["--target-unverified", "--emergency"],
                      ["--target-unverified", "--emergency", "--reason", "  "],
                      ["--scheduled", "--emergency", "--reason", "noc"]):
            with self.subTest(extra=extra):
                args = SELECT.parse_args(
                    ["select", "--repo", "o/r", "--target", A,
                     "--freeze-window", "8-18", *extra]
                )
                self.assertEqual(SELECT._run_select(args, fetch, now=now), 1)

    def test_scheduled_select_checks_head_and_defers_on_red_without_error(self):
        out, _ = self.env()

        def fetch(path):
            if path.startswith("repos/o/r/commits/"):
                return {"sha": A, "commit": {"committer": {"date": "2026-07-01T05:00:00Z"}}}
            return {"workflow_runs": [run("completed", "failure")]}

        args = SELECT.parse_args(
            ["select", "--repo", "o/r", "--target", A, "--scheduled",
             "--freeze-window", "0-7"]
        )
        now = datetime(2026, 7, 1, 5, 15, tzinfo=timezone.utc)
        self.assertEqual(SELECT._run_select(args, fetch, now=now), 0)
        text = out.read_text()
        self.assertIn("defer=true", text)
        self.assertIn("hold_alert=HEAD maina ma bramkę CI Gate = failure", text)

    def night_fetch(self, live_to_head_dates, head=B, gate="success"):
        def fetch(path):
            if path.startswith("repos/o/r/commits/"):
                return {"sha": head}
            if "/compare/" in path:
                return {
                    "status": "ahead",
                    "commits": [
                        {"commit": {"committer": {"date": date}}}
                        for date in live_to_head_dates
                    ],
                }
            return {"workflow_runs": [run("completed", gate, sha=head)]}

        return fetch

    def night_args(self, live=A):
        return SELECT.parse_args(
            ["night-check", "--repo", "o/r", "--live", live, "--freeze-window", "8-18"]
        )

    def test_night_check_alerts_on_merges_older_than_this_mornings_seven(self):
        out, _ = self.env()
        # 12:00 w Warszawie; merge z 13.10 15:00 nie wjechał nocą.
        fetch = self.night_fetch(["2026-07-13T13:00:00Z", "2026-07-14T08:00:00Z"])
        now = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(SELECT._run_night_check(self.night_args(), fetch, now=now), 0)
        text = out.read_text()
        self.assertIn("checked=true", text)
        self.assertIn("night_alert=1 commit", text)

    def test_night_check_is_quiet_for_todays_merges_and_live_head(self):
        out, _ = self.env()
        fetch = self.night_fetch(["2026-07-14T06:30:00Z"])  # 08:30 dziś
        now = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(SELECT._run_night_check(self.night_args(), fetch, now=now), 0)
        self.assertIn("night_alert=\n", out.read_text())

        out, _ = self.env()
        self.assertEqual(
            SELECT._run_night_check(self.night_args(live=B), self.night_fetch([]), now=now), 0
        )
        self.assertIn("checked=true", out.read_text())
        self.assertIn("night_alert=\n", out.read_text())

    def test_night_check_skips_during_the_window_and_on_red_head(self):
        def no_api(path):
            raise AssertionError("w oknie wdrożeń nie sprawdzamy")

        out, _ = self.env()
        night = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)  # 22:00
        self.assertEqual(SELECT._run_night_check(self.night_args(), no_api, now=night), 0)
        self.assertIn("checked=false", out.read_text())

        # Sobota w południe to też okno wdrożeń — nocy nie oceniamy.
        out, _ = self.env()
        saturday = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(SELECT._run_night_check(self.night_args(), no_api, now=saturday), 0)
        self.assertIn("checked=false", out.read_text())

        out, _ = self.env()
        day = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
        red = self.night_fetch(["2026-07-13T13:00:00Z"], gate="failure")
        self.assertEqual(SELECT._run_night_check(self.night_args(), red, now=day), 0)
        self.assertIn("checked=false", out.read_text())

    def test_missing_gate_alerts_only_after_an_hour(self):
        out, _ = self.env()

        def fetch(path):
            if path.startswith("repos/o/r/commits/"):
                return {"sha": B, "commit": {"committer": {"date": "2026-07-01T10:00:00Z"}}}
            return {"workflow_runs": []}

        args = SELECT.parse_args(["hold-check", "--repo", "o/r"])
        SELECT._run_hold_check(args, fetch, now=datetime(2026, 7, 1, 10, 30, tzinfo=timezone.utc))
        self.assertIn("hold_alert=\n", out.read_text())
        SELECT._run_hold_check(args, fetch, now=datetime(2026, 7, 1, 11, 30, tzinfo=timezone.utc))
        self.assertIn("hold_alert=HEAD maina nie ma przebiegu bramki CI Gate od 90 min", out.read_text())

    def test_accept_exports_accepted_sha_and_api_errors_are_retryable(self):
        _, env = self.env()
        self.assertEqual(
            SELECT.main(["accept", "--repo", "o/r", "--release", A, "--live", A], fetch=lambda p: {}), 0
        )
        self.assertEqual(env.read_text(), f"ACCEPTED_SHA={A}\n")

        def broken(path):
            raise urllib.error.URLError("down")

        code = SELECT.main(["accept", "--repo", "o/r", "--release", A, "--live", B], fetch=broken)
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()

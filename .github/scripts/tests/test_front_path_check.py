import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location(
    "front_path_check", Path(__file__).parents[1] / "front_path_check.py"
)
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)

SHA = "a" * 40


def front(version=(200, b'{"sha": "%s"}' % SHA.encode()), callback=(302, "https://app/login?error=x"), login=200):
    def get(url, host=None):
        if url.endswith("/version.json"):
            return version[0], {}, version[1]
        if paths.CALLBACK_PATH in url:
            return callback[0], ({"location": callback[1]} if callback[1] else {}), b""
        return login, {}, b""

    return get


class CheckPathsTests(unittest.TestCase):
    def test_healthy_front_has_no_failures(self):
        self.assertEqual(paths.check_paths(front(), "https://app", None, SHA), [])

    def test_backend_unreachable_is_named(self):
        failures = paths.check_paths(front(callback=(302, "https://app/login?error=backend_unreachable")), "https://app", None, SHA)
        self.assertEqual(len(failures), 1)
        self.assertIn("nie widzi backendu", failures[0])

    def test_callback_without_redirect_is_a_failure(self):
        for callback in [(502, ""), (200, ""), (429, ""), (0, "")]:
            with self.subTest(callback=callback):
                self.assertTrue(paths.check_paths(front(callback=callback), "https://app", None, SHA))

    def test_old_container_or_broken_version_is_a_failure(self):
        cases = [(200, b'{"sha": "' + b"b" * 40 + b'"}'), (200, b"<html>"), (404, b"")]
        for version in cases:
            with self.subTest(version=version):
                self.assertTrue(paths.check_paths(front(version=version), "https://app", None, SHA))

    def test_commit_is_optional_after_deploy(self):
        self.assertEqual(paths.check_paths(front(version=(200, b"{}")), "https://app", None, ""), [])

    def test_login_page_must_render(self):
        self.assertTrue(paths.check_paths(front(login=500), "https://app", None, SHA))

    def test_host_header_is_passed_for_the_test_address(self):
        seen = []

        def get(url, host=None):
            seen.append(host)
            return front()(url, host)

        paths.check_paths(get, "http://203.0.113.7", paths.CHECK_HOST, SHA)
        self.assertEqual(set(seen), {paths.CHECK_HOST})


class FetchTests(unittest.TestCase):
    def test_broken_response_is_a_failed_probe_not_a_crash(self):
        import http.client
        from unittest import mock

        with mock.patch.object(paths._OPENER, "open", side_effect=http.client.RemoteDisconnected("x")):
            self.assertEqual(paths.fetch("https://app/login"), (0, {}, b""))
        with mock.patch.object(paths._OPENER, "open", side_effect=http.client.IncompleteRead(b"")):
            self.assertEqual(paths.fetch("https://app/login"), (0, {}, b""))


class WatchTests(unittest.TestCase):
    def test_two_bad_rounds_in_a_row_stop_the_watch(self):
        calls = []

        def get(url, host=None):
            calls.append(url)
            return front(callback=(502, ""))(url, host)

        failures = paths.watch(get, "https://app", SHA, seconds=60, every=5, sleep=lambda _s: None)
        self.assertTrue(failures)
        self.assertEqual(len(calls), 6, "przerwanie po drugiej rundzie, nie po 12")

    def test_alternating_blips_do_not_fail(self):
        state = {"n": 0}

        def get(url, host=None):
            if paths.CALLBACK_PATH in url:
                state["n"] += 1
                if state["n"] % 2:
                    return 502, {}, b""
            return front()(url, host)

        self.assertEqual(paths.watch(get, "https://app", SHA, seconds=20, every=5, sleep=lambda _s: None), [])

    def test_bad_last_round_is_reported(self):
        state = {"n": 0}

        def get(url, host=None):
            if paths.CALLBACK_PATH in url:
                state["n"] += 1
                if state["n"] == 4:
                    return 502, {}, b""
            return front()(url, host)

        self.assertTrue(paths.watch(get, "https://app", SHA, seconds=20, every=5, sleep=lambda _s: None))


if __name__ == "__main__":
    unittest.main()

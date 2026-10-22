"""Offline contract tests: no SSH, Docker, database or production data."""
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / "scripts/staging/clone_from_hetzner.py"
spec = importlib.util.spec_from_file_location("staging_clone", MODULE)
clone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clone)


class Pipe(io.BytesIO):
    def close(self):
        self.saved = self.getvalue()
        super().close()


class Process:
    def __init__(self, code=0, stdin=None):
        self.code = code
        self.stdin = stdin

    def wait(self):
        return self.code

    def poll(self):
        return self.code


class CloneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "private"
        self.args = clone.parser().parse_args([
            "--ssh-host", "operator@production.example", "--source-container", "a" * 64,
            "--target-db", "nexus_staging_test", "--output-root", str(self.root)])
        self.tool = patch.object(clone.shutil, "which", return_value="/mock/tool")
        self.tool.start()
        self.addCleanup(self.tool.stop)

    def test_nonloopback_and_unsafe_inputs_rejected_before_any_process(self):
        cases = [("target_host", "production.example"), ("target_host", "localhost"),
                 ("target_db", "nexus"), ("target_db", "nexus_staging_a'; DROP DATABASE nexus;--"),
                 ("target_user", "--host=production"), ("source_db", "dbname=nexus host=evil"),
                 ("source_container", "postgres; id"), ("source_container", "postgres"),
                 ("ssh_host", "-oProxyCommand=evil"), ("ssh_host", "user@host;id"), ("ssh_identity", Path("-bad"))]
        with patch.object(clone.subprocess, "run") as run:
            for field, value in cases:
                with self.subTest(field=field, value=value):
                    args = clone.argparse.Namespace(**vars(self.args))
                    setattr(args, field, value)
                    with self.assertRaises(clone.CloneError):
                        clone.execute(args)
            run.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_existing_database_is_untouched_before_dump(self):
        with patch.object(clone.subprocess, "run", return_value=clone.subprocess.CompletedProcess([], 0, b"1\n")) as run:
            with self.assertRaisesRegex(clone.CloneError, "already exists"):
                clone.execute(self.args)
        self.assertEqual(len(run.call_args_list), 1)
        self.assertNotIn("CREATE", " ".join(run.call_args.args[0]))
        self.assertFalse(self.root.exists())

    def test_failed_dump_never_restores_and_removes_partial_file(self):
        def failed(command, **kwargs):
            kwargs["stdout"].write(b"PGDMPpartial")
            return clone.subprocess.CompletedProcess(command, 1)
        with patch.object(clone, "ensure_absent"), patch.object(clone.subprocess, "run", side_effect=failed), patch.object(clone, "restore") as restore:
            with self.assertRaises(clone.CloneError):
                clone.execute(self.args)
            restore.assert_not_called()
        self.assertEqual(list(self.root.rglob("baseline.dump")), [])

    def test_source_failure_is_classified_without_exposing_diagnostics(self):
        self.root.mkdir(mode=0o700)
        archive = self.root / "baseline.dump"

        def interrupted(command, **kwargs):
            kwargs["stdout"].write(b"PGDMPpartial")
            return clone.subprocess.CompletedProcess(
                command, 1, stderr=b"server closed the connection; private-record-value"
            )

        with patch.object(clone.subprocess, "run", side_effect=interrupted):
            with self.assertRaisesRegex(clone.CloneError, "source_connection_closed") as result:
                clone.dump(self.args, archive)
        self.assertNotIn("private-record-value", str(result.exception))
        self.assertFalse(archive.exists())

    def test_dump_only_preserves_private_baseline_and_manifest(self):
        self.args.dump_only = True
        def successful(command, **kwargs):
            self.assertEqual(command[:2], ["ssh", "-T"])
            self.assertIn("BatchMode=yes", command)
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("ServerAliveInterval=15", command)
            self.assertIn("ServerAliveCountMax=4", command)
            kwargs["stdout"].write(b"PGDMPbaseline-fixture")
            return clone.subprocess.CompletedProcess(command, 0)
        with patch.object(clone.subprocess, "run", side_effect=successful), patch.object(clone, "restore") as restore:
            path = clone.execute(self.args)
            restore.assert_not_called()
        manifest = json.loads(path.read_text())
        self.assertEqual(manifest["status"], "dumped")
        self.assertFalse(manifest["application_started"])
        for directory in (self.root, path.parent):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for file in (path, Path(manifest["dump"]["path"])):
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertEqual(clone.digest(Path(manifest["dump"]["path"])), manifest["dump"]["sha256"])

    def test_preflight_has_no_side_effects(self):
        self.args.dry_run = True
        with patch.object(clone.subprocess, "run") as run, patch.object(clone.subprocess, "Popen") as popen:
            clone.execute(self.args)
            run.assert_not_called()
            popen.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_existing_insecure_output_and_symlinks_are_rejected(self):
        self.root.mkdir(mode=0o755)
        with self.assertRaises(clone.CloneError):
            clone.validate(self.args)
        self.root.rmdir()
        self.root.symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaises(clone.CloneError):
            clone.validate(self.args)

    def test_ambient_libpq_override_is_removed(self):
        with patch.dict(os.environ, {"PGHOSTADDR": "203.0.113.1", "PGSERVICE": "production", "PGOPTIONS": "unsafe", "PGPASSWORD": "fixture"}):
            env = clone.local_env()
        self.assertNotIn("PGHOSTADDR", env)
        self.assertNotIn("PGSERVICE", env)
        self.assertNotIn("PGOPTIONS", env)
        self.assertEqual(env["PGPASSWORD"], "fixture")

    def test_restore_failure_never_commits_or_starts_application(self):
        pipe = Pipe()
        consumer, producer = Process(0, pipe), Process(1)
        with patch.object(clone, "ensure_absent"), patch.object(clone, "checked") as checked, patch.object(clone.subprocess, "Popen", side_effect=[consumer, producer]) as popen:
            with self.assertRaisesRegex(clone.CloneError, "rolled back"):
                clone.restore(self.args, Path("/private/baseline.dump"), b"DELETE FROM fixture;\n")
        self.assertEqual(pipe.saved, b"BEGIN;\n")
        self.assertEqual(len(popen.call_args_list), 2)
        self.assertIn("--exit-on-error", popen.call_args_list[1].args[0])
        self.assertIn("CREATE DATABASE", checked.call_args.args[0][-1])

    def test_restore_and_sanitize_commit_together(self):
        pipe = Pipe()
        with patch.object(clone, "ensure_absent"), patch.object(clone, "checked"), patch.object(clone.subprocess, "Popen", side_effect=[Process(0, pipe), Process(0)]):
            clone.restore(self.args, Path("/private/baseline.dump"), b"DELETE FROM fixture;\n")
        self.assertTrue(pipe.saved.startswith(b"BEGIN;\n"))
        self.assertTrue(pipe.saved.endswith(b"COMMIT;\n"))
        self.assertIn(b"DELETE FROM fixture;", pipe.saved)

    def test_explicit_ssh_identity_is_passed_without_reading_key(self):
        key = Path(self.temp.name).resolve() / "identity"
        key.touch(mode=0o600)
        self.args.ssh_identity = key
        clone.validate(self.args)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("key must not be read")):
            command = clone.remote_command(self.args)
        self.assertIn("IdentitiesOnly=yes", command)
        self.assertEqual(command[command.index("-i") + 1], str(key))

    def test_restore_failure_retains_dump_and_failed_manifest(self):
        def fixture_dump(args, path):
            clone.write_private(path, b"PGDMPfixture")
        with patch.object(clone, "ensure_absent"), patch.object(clone, "dump", side_effect=fixture_dump), patch.object(clone, "restore", side_effect=clone.CloneError("fixture failure")):
            with self.assertRaises(clone.CloneError):
                clone.execute(self.args)
        manifest = json.loads(next(self.root.rglob("manifest.json")).read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(manifest["application_started"])
        self.assertFalse(manifest["promotion_baseline"])
        self.assertTrue(Path(manifest["dump"]["path"]).is_file())

    def saved_fixture(self):
        self.root.mkdir(mode=0o700)
        archive = self.root / "baseline.dump"
        clone.write_private(archive, b"PGDMPfixture")
        manifest = {"schema_version": 1, "kind": "nexus-staging-clone-baseline", "status": "dumped",
                    "dump": {"path": str(archive), "sha256": clone.digest(archive), "bytes": archive.stat().st_size, "format": "custom"},
                    "sanitize": {"sha256": clone.digest(clone.REPO / "scripts/staging/sanitize.sql")}}
        path = self.root / "manifest.json"
        clone.write_private(path, json.dumps(manifest).encode())
        args = clone.parser().parse_args(["--restore-manifest", str(path), "--target-db", "nexus_staging_resume"])
        return args, path, archive, manifest

    def test_any_other_git_repository_is_rejected(self):
        other = Path(self.temp.name).resolve() / "unrelated-repo"
        other.mkdir()
        (other / ".git").write_text("gitdir: elsewhere")
        self.args.output_root = other / "artifacts"
        with self.assertRaisesRegex(clone.CloneError, "every Git"):
            clone.validate(self.args)

    def test_lock_timeout_is_bounded_on_production(self):
        self.assertIn("--lock-wait-timeout=5s", clone.remote_command(self.args)[-1])

    def test_resume_does_not_ssh_and_preserves_source_manifest(self):
        args, path, archive, manifest = self.saved_fixture()
        original = path.read_bytes()
        with patch.object(clone, "restore") as restore, patch.object(clone.subprocess, "run") as run:
            receipt_path = clone.execute(args)
            run.assert_not_called()
            restore.assert_called_once()
            self.assertEqual(restore.call_args.args[1], archive)
        self.assertEqual(path.read_bytes(), original)
        self.assertNotEqual(receipt_path, path)
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["status"], "restored_sanitized")
        self.assertFalse(receipt["application_started"])
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)

    def test_resume_refuses_tampered_archive_and_sanitizer_before_restore(self):
        args, path, archive, manifest = self.saved_fixture()
        with patch.object(clone, "restore") as restore:
            archive.write_bytes(b"PGDMPchanged")
            with self.assertRaises(clone.CloneError):
                clone.execute(args)
            archive.write_bytes(b"PGDMPfixture")
            manifest["sanitize"]["sha256"] = "0" * 64
            path.write_text(json.dumps(manifest))
            with self.assertRaises(clone.CloneError):
                clone.execute(args)
            restore.assert_not_called()

    def test_resume_refuses_missing_header_even_when_digest_matches(self):
        args, path, archive, manifest = self.saved_fixture()
        archive.write_bytes(b"not-a-custom-archive")
        manifest["dump"]["sha256"] = clone.digest(archive)
        manifest["dump"]["bytes"] = archive.stat().st_size
        path.write_text(json.dumps(manifest))
        with patch.object(clone, "restore") as restore:
            with self.assertRaisesRegex(clone.CloneError, "custom-format"):
                clone.execute(args)
            restore.assert_not_called()

    def test_resume_existing_db_is_refused_without_create_or_archive_change(self):
        args, path, archive, manifest = self.saved_fixture()
        original = path.read_bytes()
        with patch.object(clone.subprocess, "run", return_value=clone.subprocess.CompletedProcess([], 0, b"1")) as run, patch.object(clone.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(clone.CloneError, "already exists"):
                clone.execute(args)
            popen.assert_not_called()
            self.assertEqual(run.call_count, 1)
            self.assertNotIn("CREATE", " ".join(run.call_args.args[0]))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(archive.read_bytes(), b"PGDMPfixture")

    def test_resume_refuses_wrong_status_and_private_permissions(self):
        args, path, archive, manifest = self.saved_fixture()
        with patch.object(clone, "restore") as restore:
            archive.chmod(0o644)
            with self.assertRaises(clone.CloneError):
                clone.execute(args)
            archive.chmod(0o600)
            manifest["status"] = "restored_sanitized"
            path.write_text(json.dumps(manifest))
            with self.assertRaises(clone.CloneError):
                clone.execute(args)
            restore.assert_not_called()

    def container_identity(self, **extra):
        return {"id": "b" * 64, "project": "nexus-staging", "service": "postgres",
                "running": True, "ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5433"}]}, **extra}

    def container_response(self, command, **kwargs):
        if command[1:3] == ["context", "show"]:
            data = b"desktop-linux\n"
        elif command[1:3] == ["context", "inspect"]:
            data = b"unix:///private/tmp/fixture-docker.sock\n"
        elif "inspect" in command:
            data = json.dumps(self.container_identity()).encode()
        elif command[-1] == "--version":
            data = b"psql (PostgreSQL) 16.4\n"
        else:
            data = b""
        return clone.subprocess.CompletedProcess(command, 0, data)

    def test_container_adapter_rejects_remote_env_before_any_process(self):
        self.args.local_postgres_container = "b" * 64
        with patch.dict(os.environ, {"DOCKER_HOST": "ssh://production"}), patch.object(clone.subprocess, "run") as run:
            with self.assertRaisesRegex(clone.CloneError, "DOCKER_HOST"):
                clone.execute(self.args)
            run.assert_not_called()

    def test_container_remote_context_rejected_before_inspect_or_exec(self):
        self.args.local_postgres_container = "b" * 64
        with patch.object(clone.subprocess, "run", side_effect=[
                clone.subprocess.CompletedProcess([], 0, b"remote\n"),
                clone.subprocess.CompletedProcess([], 0, b"tcp://production:2376\n")]) as run:
            with self.assertRaisesRegex(clone.CloneError, "unix socket"):
                clone.prepare_local_target(self.args)
            self.assertEqual(run.call_count, 2)
            self.assertFalse(any("exec" in call.args[0] for call in run.call_args_list))

    def test_wrong_container_labels_never_execute_postgres(self):
        self.args.local_postgres_container = "b" * 64
        def wrong(command, **kwargs):
            if "inspect" in command and "--type" in command:
                identity = self.container_identity(project="production")
                return clone.subprocess.CompletedProcess(command, 0, json.dumps(identity).encode())
            return self.container_response(command, **kwargs)
        with patch.object(clone.subprocess, "run", side_effect=wrong) as run:
            with self.assertRaisesRegex(clone.CloneError, "nexus-staging"):
                clone.prepare_local_target(self.args)
            self.assertFalse(any("exec" in call.args[0] for call in run.call_args_list))

    def test_container_mode_requires_no_native_clients_and_pins_local_socket(self):
        args, path, archive, manifest = self.saved_fixture()
        args.local_postgres_container = "b" * 64
        seen_tools = []
        def which(name):
            seen_tools.append(name)
            return "/mock/docker" if name == "docker" else None
        with patch.object(clone.shutil, "which", side_effect=which), patch.object(clone.subprocess, "run", side_effect=self.container_response), patch.object(clone, "restore") as restore:
            receipt_path = clone.execute(args)
            restore.assert_called_once()
        self.assertEqual(seen_tools, ["docker"])
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["target"]["container_id"], "b" * 64)
        self.assertEqual(receipt["target"]["project"], "nexus-staging")
        with patch.object(clone.subprocess, "run", side_effect=self.container_response):
            clone.prepare_local_target(args)
        command = clone.pg_command(args, args.target_db)
        self.assertEqual(command[:3], ["docker", "--host", "unix:///private/tmp/fixture-docker.sock"])
        self.assertIn("-i", command)
        self.assertNotIn("-t", command)
        self.assertEqual(command[command.index("--host", 3) + 1], "/var/run/postgresql")

    def test_container_wrong_postgres_version_refused_before_database_commands(self):
        self.args.local_postgres_container = "b" * 64
        def wrong_version(command, **kwargs):
            if command[-1] == "--version":
                return clone.subprocess.CompletedProcess(command, 0, b"psql (PostgreSQL) 17.1")
            return self.container_response(command, **kwargs)
        with patch.object(clone.subprocess, "run", side_effect=wrong_version) as run:
            with self.assertRaisesRegex(clone.CloneError, "PostgreSQL 16"):
                clone.prepare_local_target(self.args)
        self.assertFalse(any("CREATE DATABASE" in " ".join(call.args[0]) for call in run.call_args_list))
        self.assertFalse(hasattr(self.args, "_docker_command"))

    def test_dump_only_never_inspects_container_or_requires_docker(self):
        self.args.dump_only = True
        self.args.local_postgres_container = "b" * 64
        seen = []
        def which(name):
            seen.append(name)
            return "/mock/ssh" if name == "ssh" else None
        def successful(command, **kwargs):
            self.assertEqual(command[0], "ssh")
            kwargs["stdout"].write(b"PGDMPfixture")
            return clone.subprocess.CompletedProcess(command, 0)
        with patch.object(clone.shutil, "which", side_effect=which), patch.object(clone.subprocess, "run", side_effect=successful):
            clone.execute(self.args)
        self.assertEqual(seen, ["ssh"])

    def test_container_restore_failure_streams_archive_stdin_without_commit(self):
        args, path, archive, manifest = self.saved_fixture()
        args.local_postgres_container = "b" * 64
        original = path.read_bytes()
        pipe = Pipe()
        with patch.object(clone.subprocess, "run", side_effect=self.container_response), patch.object(clone.subprocess, "Popen", side_effect=[Process(0, pipe), Process(1)]) as popen:
            with self.assertRaisesRegex(clone.CloneError, "rolled back"):
                clone.execute(args)
        producer = popen.call_args_list[1]
        self.assertEqual(producer.args[0][-1], "--file=-")
        self.assertNotIn(str(archive), producer.args[0])
        self.assertEqual(producer.kwargs["stdin"].name, str(archive))
        self.assertEqual(pipe.saved, b"BEGIN;\n")
        self.assertEqual(path.read_bytes(), original)
        receipt = json.loads(next(self.root.glob("restore-receipt-*.json")).read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["target"]["container_port"], 5432)

    def test_real_sanitizer_has_only_outer_restore_transaction(self):
        sql = clone.sanitization_sql(clone.REPO / "scripts/staging/sanitize.sql")
        self.assertNotIn(b"BEGIN;", sql)
        self.assertNotIn(b"COMMIT;", sql)
        self.assertIn(b"UPDATE m365_connections", sql)
        self.assertIn(b"DELETE FROM graph_subscriptions", sql)


if __name__ == "__main__":
    unittest.main()

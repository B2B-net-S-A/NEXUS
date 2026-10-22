#!/usr/bin/env python3
"""Capture a production dump and restore ONLY into a new local DB.

No application is started and no existing database is replaced. The unencrypted
dump contains production data: keep the private output directory on encrypted
local storage. SSH only executes pg_dump in the explicitly selected DB container.
Local authentication uses libpq's .pgpass or PGPASSWORD, never command arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
import uuid
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")
SSH_HOST = re.compile(r"(?:[a-z_][a-z0-9_-]*@)?[A-Za-z0-9][A-Za-z0-9.-]*\Z")
CONTAINER_ID = re.compile(r"[a-f0-9]{64}\Z")


class CloneError(Exception):
    """Safe error text; never includes process stderr or row data."""


def identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise CloneError("Use simple lowercase PostgreSQL identifiers only")
    return value


def local_env() -> dict[str, str]:
    # Do not let ambient PGHOSTADDR/PGSERVICE/PGOPTIONS override the target.
    return {k: v for k, v in os.environ.items()
            if (not k.startswith("PG") or k in {"PGPASSWORD", "PGPASSFILE"})
            and not k.startswith("DOCKER_")}


def artifact_path(path: Path) -> Path:
    if ".." in path.parts:
        raise CloneError("Artifact path must not contain parent traversal")
    path = path.expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise CloneError("Artifact path must not contain symlinks")
    if any((p / ".git").exists() for p in (path, *path.parents)):
        raise CloneError("Artifacts must remain outside every Git repository")
    return path


def private_file(path: Path) -> None:
    info = path.stat()
    parent = path.parent.stat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid() or not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) != 0o700 or parent.st_uid != os.getuid()):
        raise CloneError("Manifest/archive must be owned by you, mode 0600 in a private 0700 directory")


def validate(args: argparse.Namespace) -> None:
    if args.target_host not in {"127.0.0.1", "::1"}:
        raise CloneError("Target must be the literal loopback address 127.0.0.1 or ::1")
    if not 1 <= args.target_port <= 65535:
        raise CloneError("Invalid target port")
    identifier(args.target_db)
    if not args.target_db.startswith("nexus_staging_"):
        raise CloneError("Target database must start with nexus_staging_")
    identifier(args.target_user)
    if args.local_postgres_container:
        if not CONTAINER_ID.fullmatch(args.local_postgres_container):
            raise CloneError("Local PostgreSQL container must be an explicit full container ID")
        if not args.dump_only and any(os.environ.get(name) for name in ("DOCKER_HOST", "DOCKER_CONTEXT")):
            raise CloneError("Unset DOCKER_HOST and DOCKER_CONTEXT before selecting a local target")
    if args.restore_manifest is not None:
        if args.dump_only or args.ssh_host or args.source_container or args.ssh_identity:
            raise CloneError("Restore-manifest cannot be combined with dump/SSH options")
        args.restore_manifest = artifact_path(args.restore_manifest)
        return
    identifier(args.source_db)
    identifier(args.source_user)
    if not args.ssh_host or not SSH_HOST.fullmatch(args.ssh_host) or ".." in args.ssh_host:
        raise CloneError("Invalid SSH destination; options and shell syntax are forbidden")
    if not args.source_container or not CONTAINER_ID.fullmatch(args.source_container):
        raise CloneError("Source container must be an explicit full 64-character container ID")
    if args.ssh_identity is not None:
        identity = args.ssh_identity.expanduser()
        if str(identity).startswith("-") or not identity.is_absolute() or not identity.is_file():
            raise CloneError("SSH identity must be an existing absolute file path")
        args.ssh_identity = identity
    root = artifact_path(args.output_root)
    if root.is_relative_to(REPO) or REPO.is_relative_to(root):
        raise CloneError("Output directory must be outside the repository")
    if root.exists():
        mode = root.stat().st_mode
        if not stat.S_ISDIR(mode) or stat.S_IMODE(mode) != 0o700 or root.stat().st_uid != os.getuid():
            raise CloneError("Existing output directory must be owned by you and mode 0700")
    args.output_root = root


def remote_command(args: argparse.Namespace) -> list[str]:
    command = ["docker", "exec", args.source_container, "pg_dump",
               "--host=/var/run/postgresql", "--port=5432",
               "--username", args.source_user, "--dbname", args.source_db,
               "--format=custom", "--no-owner", "--no-acl", "--no-password",
               "--lock-wait-timeout=5s"]
    ssh = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
           "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
    if args.ssh_identity is not None:
        ssh += ["-o", "IdentitiesOnly=yes", "-i", str(args.ssh_identity)]
    return ssh + ["--", args.ssh_host, shlex.join(command)]


def pg_command(args: argparse.Namespace, database: str) -> list[str]:
    container = args.local_postgres_container and not args.dump_only
    prefix = docker_exec(args) if container else []
    return prefix + ["psql", "-X", "--no-password", "--host",
            "/var/run/postgresql" if container else args.target_host,
            "--port", "5432" if container else str(args.target_port), "--username", args.target_user,
            "--dbname", database, "--set", "ON_ERROR_STOP=1"]


def docker_exec(args: argparse.Namespace) -> list[str]:
    if not getattr(args, "_docker_command", None):
        raise CloneError("Local Docker target has not been verified")
    # Pin the daemon and container; clear libpq redirection inherited inside it.
    return args._docker_command + ["exec", "-i", "-e", "PGHOSTADDR=", "-e", "PGSERVICE=",
                                   "-e", "PGSERVICEFILE=", "-e", "PGOPTIONS=",
                                   args.local_postgres_container]


def prepare_local_target(args: argparse.Namespace) -> None:
    if not args.local_postgres_container or args.dump_only or getattr(args, "_docker_command", None):
        return
    if any(os.environ.get(name) for name in ("DOCKER_HOST", "DOCKER_CONTEXT")):
        raise CloneError("Ambiguous Docker environment; no target commands were executed")
    context = checked(["docker", "context", "show"], capture=True).decode().strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", context):
        raise CloneError("Invalid effective Docker context")
    endpoint = checked(["docker", "context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}"], capture=True).decode().strip()
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "unix" or parsed.netloc or not parsed.path.startswith("/")
            or parsed.query or parsed.fragment or "%" in parsed.path or "\n" in endpoint):
        raise CloneError("Docker target must use an explicit local unix socket")
    pinned = ["docker", "--host", endpoint]
    # Do not inspect Config.Env: it contains credentials. Fetch only safe identity.
    template = '{"id":{{json .Id}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"running":{{json .State.Running}},"ports":{{json .NetworkSettings.Ports}}}'
    try:
        info = json.loads(checked(pinned + ["inspect", "--type", "container", "--format", template,
                                          args.local_postgres_container], capture=True))
        ports = info["ports"]["5432/tcp"]
        if (info["id"] != args.local_postgres_container or info["running"] is not True
                or info["project"] != "nexus-staging"
                or info["service"] != "postgres"
                or not ports or any(p["HostIp"] not in {"127.0.0.1", "::1"} for p in ports)
                or not any(p["HostIp"] == args.target_host and p["HostPort"] == str(args.target_port) for p in ports)):
            raise CloneError("Local target is not the running loopback nexus-staging/postgres service")
    except (ValueError, TypeError, KeyError):
        raise CloneError("Invalid local container identity") from None
    args._docker_command = pinned
    try:
        for tool in ("psql", "pg_restore"):
            version = checked(docker_exec(args) + [tool, "--version"], capture=True)
            if not re.search(rb"\(PostgreSQL\) 16(?:\.|\s|$)", version):
                raise CloneError("Local container must supply PostgreSQL 16 clients")
    except BaseException:
        del args._docker_command
        raise


def target_info(args: argparse.Namespace) -> dict:
    info = {"host": args.target_host, "port": args.target_port, "database": args.target_db}
    if args.local_postgres_container and not args.dump_only:
        info.update({"mode": "local-container", "container_id": args.local_postgres_container,
                     "project": "nexus-staging", "service": "postgres", "container_port": 5432,
                     "connection": "unix:/var/run/postgresql"})
    return info


def checked(command: list[str], *, capture: bool = False) -> bytes:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=local_env(), check=False)
    except OSError:
        raise CloneError("Required command could not be executed") from None
    if result.returncode:
        raise CloneError("PostgreSQL operation failed; no application was started")
    return result.stdout if capture else b""


def ensure_absent(args: argparse.Namespace) -> None:
    prepare_local_target(args)
    result = checked(pg_command(args, "postgres") + ["-At", "-c",
                     f"SELECT 1 FROM pg_database WHERE datname = '{args.target_db}'"], capture=True)
    if result.strip():
        raise CloneError("Target database already exists; it was left untouched")


def sanitization_sql(path: Path) -> bytes:
    """Embed the established sanitizer in the same transaction as the restore."""
    lines = path.read_text().splitlines()
    active = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("--")]
    if active.count("BEGIN;") != 1 or active.count("COMMIT;") != 1:
        raise CloneError("Sanitizer must contain exactly one BEGIN/COMMIT transaction")
    output = []
    for line in lines:
        stripped = line.strip()
        if stripped in {"BEGIN;", "COMMIT;", r"\set ON_ERROR_STOP on"}:
            continue
        if not stripped.startswith("--") and ("\\" in line or re.search(
                r"\b(BEGIN|COMMIT|ROLLBACK|START\s+TRANSACTION)\b", line, re.I)):
            raise CloneError("Unsupported transaction or psql command in sanitizer")
        output.append(line)
    return ("\n".join(output) + "\n").encode()


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dump(args: argparse.Namespace, path: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            result = subprocess.run(remote_command(args), stdout=out, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, env=local_env(), check=False)
            out.flush()
            os.fsync(out.fileno())
        with path.open("rb") as header:
            valid_header = header.read(5) == b"PGDMP"
        if result.returncode:
            # Classify diagnostics without emitting PostgreSQL messages, which
            # may contain production table names or other sensitive context.
            diagnostic = (getattr(result, "stderr", None) or b"").lower()
            reasons = {
                b"no such container": "source_container_changed",
                b"permission denied": "source_permission_denied",
                b"lock timeout": "source_lock_timeout",
                b"terminating connection": "source_connection_terminated",
                b"server closed the connection": "source_connection_closed",
                b"connection reset": "source_connection_reset",
                b"broken pipe": "source_connection_broken_pipe",
                b"no space left": "source_no_space",
            }
            reason = next((code for marker, code in reasons.items() if marker in diagnostic), "source_dump_failed")
            raise CloneError(f"{reason} (exit {result.returncode}); incomplete archive removed")
        if not valid_header:
            raise CloneError("source_archive_format_invalid; incomplete archive removed")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def restore(args: argparse.Namespace, path: Path, sanitize: bytes) -> None:
    # CREATE DATABASE is intentionally outside the restore transaction. A race
    # loses at CREATE, never drops/replaces another database. Failed restores
    # retain a new empty DB for explicit inspection; no automatic app startup.
    ensure_absent(args)
    checked(pg_command(args, "postgres") + ["-c", f'CREATE DATABASE "{args.target_db}" TEMPLATE template0'])
    consumer = subprocess.Popen(pg_command(args, args.target_db), stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=local_env())
    producer = None
    try:
        consumer.stdin.write(b"BEGIN;\n")
        consumer.stdin.flush()
        if args.local_postgres_container:
            # Archive enters the local container only through stdin; no host paths/mounts.
            with path.open("rb") as archive:
                producer = subprocess.Popen(docker_exec(args) + ["pg_restore", "--exit-on-error", "--no-owner", "--no-acl", "--file=-"],
                                            stdin=archive, stdout=consumer.stdin,
                                            stderr=subprocess.DEVNULL, env=local_env())
        else:
            producer = subprocess.Popen(["pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
                                         "--file=-", str(path)], stdout=consumer.stdin,
                                        stderr=subprocess.DEVNULL, env=local_env())
        if producer.wait() != 0:
            raise CloneError("pg_restore failed; transaction was rolled back and no application was started")
        consumer.stdin.write(b"\n" + sanitize + b"\nCOMMIT;\n")
        consumer.stdin.close()
        if consumer.wait() != 0:
            raise CloneError("Restore/sanitization failed; no application was started")
    except BaseException:
        if producer is not None and producer.poll() is None:
            producer.terminate()
            producer.wait()
        if not consumer.stdin.closed:
            consumer.stdin.close()  # EOF without COMMIT rolls the transaction back.
        consumer.wait()
        raise


def restore_saved(args: argparse.Namespace, sanitizer: Path, sanitize: bytes) -> Path | None:
    """Verify a saved dump before touching PG; preserve its source manifest."""
    manifest_path = args.restore_manifest
    private_file(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text())
        archive = artifact_path(Path(manifest["dump"]["path"]))
        private_file(archive)
        if (manifest["schema_version"] != 1
                or manifest["kind"] != "nexus-staging-clone-baseline"
                or manifest["status"] != "dumped"
                or manifest["dump"]["format"] != "custom"
                or archive != manifest_path.parent / "baseline.dump"
                or archive.stat().st_size != manifest["dump"]["bytes"]
                or digest(archive) != manifest["dump"]["sha256"]
                or digest(sanitizer) != manifest["sanitize"]["sha256"]):
            raise CloneError("Saved manifest, archive or sanitizer does not match")
        with archive.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                raise CloneError("Saved archive is not custom-format PostgreSQL data")
    except (KeyError, TypeError, ValueError):
        raise CloneError("Invalid saved manifest") from None
    if args.dry_run:
        print("Saved-dump preflight OK; no SSH, database commands or writes")
        return None
    receipt_path = manifest_path.parent / ("restore-receipt-" + uuid.uuid4().hex + ".json")
    receipt = {
        "schema_version": 1, "kind": "nexus-staging-clone-restore-receipt",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_manifest": str(manifest_path), "source_manifest_sha256": digest(manifest_path),
        "dump_sha256": digest(archive), "sanitize_sha256": digest(sanitizer),
        "target": target_info(args),
        "status": "failed", "application_started": False,
    }
    try:
        restore(args, archive, sanitize)
        receipt["status"] = "restored_sanitized"
    finally:
        write_private(receipt_path, (json.dumps(receipt, indent=2) + "\n").encode())
    print("Saved dump restored and sanitized; no application started. Receipt: " + str(receipt_path))
    return receipt_path


def execute(args: argparse.Namespace) -> Path | None:
    validate(args)
    sanitizer = REPO / "scripts/staging/sanitize.sql"
    sanitize = sanitization_sql(sanitizer)
    local_tools = ["docker"] if args.local_postgres_container else ["psql", "pg_restore"]
    tools = local_tools if args.restore_manifest else ["ssh"] if args.dump_only else ["ssh", *local_tools]
    missing = [name for name in tools if shutil.which(name) is None]
    if missing:
        raise CloneError("Missing local tools: " + ", ".join(missing) + "; use --dump-only without local PostgreSQL")
    if args.restore_manifest:
        return restore_saved(args, sanitizer, sanitize)
    if args.dry_run:
        print("Preflight OK: validated loopback/new database, source and private output; no SSH or database commands executed")
        return None
    if not args.dump_only:
        ensure_absent(args)
    # mkdir is deliberately exclusive for each snapshot. Baseline is never overwritten.
    args.output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex
    directory = args.output_root / snapshot_id
    directory.mkdir(mode=0o700)
    archive = directory / "baseline.dump"
    dump(args, archive)
    manifest = {
        "schema_version": 1, "kind": "nexus-staging-clone-baseline", "snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "dumped",
        "source": {"ssh_host": args.ssh_host, "container_id": args.source_container, "database": args.source_db},
        "target": target_info(args),
        "dump": {"path": str(archive), "sha256": digest(archive), "bytes": archive.stat().st_size, "format": "custom"},
        "sanitize": {"path": str(sanitizer), "sha256": digest(sanitizer)},
        "baseline_preserved": True, "contains_production_data": True, "application_started": False,
        "promotion_baseline": False,  # Selected fields must be snapshotted after sanitization.

    }
    try:
        if not args.dump_only:
            restore(args, archive, sanitize)
            manifest["status"] = "restored_sanitized"
    except BaseException:
        manifest["status"] = "failed"
        raise
    finally:
        write_private(directory / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print("Baseline saved privately; application was not started. Manifest: " + str(directory / "manifest.json"))
    return directory / "manifest.json"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--restore-manifest", type=Path, help="Resume a saved dumped manifest locally; no SSH or redownload")
    p.add_argument("--ssh-host", help="Required for clone: existing SSH destination, strict known-host verification")
    p.add_argument("--ssh-identity", type=Path, help="Absolute private-key path passed to ssh; never read by this script")
    p.add_argument("--source-container", help="Required for clone: full 64-character DB container ID, never an auto-selected service")
    p.add_argument("--source-db", default="nexus")
    p.add_argument("--source-user", default="nexus")
    p.add_argument("--target-host", default="127.0.0.1", help="Literal 127.0.0.1 or ::1 only")
    p.add_argument("--target-port", type=int, default=5433)
    p.add_argument("--target-user", default="nexus")
    p.add_argument("--local-postgres-container", help="Explicit full container ID: verified local nexus-staging/postgres, no native PG clients needed")
    p.add_argument("--target-db", required=True, help="New, nonexistent nexus_staging_* database")
    p.add_argument("--output-root", type=Path, default=Path.home() / ".local/share/nexus-staging-baselines")
    p.add_argument("--dry-run", "--preflight", action="store_true", help="Validate inputs/tools only; no SSH, DB commands or writes")
    p.add_argument("--dump-only", action="store_true", help="Capture baseline only; no local PostgreSQL tools required")
    return p


def main() -> int:
    try:
        execute(parser().parse_args())
    except CloneError as error:
        print("Clone stopped safely: " + str(error) + ". No application was started.", file=sys.stderr)
        return 1
    except (OSError, BrokenPipeError):
        # Do not echo exception details: subprocess/file errors can contain data.
        print("Clone stopped safely; check target availability, tools, strict SSH authentication and inputs. No application was started.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The interactive CLI hands its one fresh token only to a private channel."""

from __future__ import annotations

import json
import os
import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import cpro_bot_run as cli


def _argv(fd: int, delivery_lead_id: int = 27) -> list[str]:
    return [
        "--interactive-draft",
        "--stage-ids",
        "101",
        "--delivery-lead-id",
        str(delivery_lead_id),
        "--request-number",
        "42511",
        "--token-fd",
        str(fd),
    ]


@pytest.fixture
def fake_interactive_flow(monkeypatch):
    @asynccontextmanager
    async def session():
        yield object()

    token = "regression_only_private_token_marker"
    create = AsyncMock(return_value=(SimpleNamespace(id=7, status="started"), token))
    monkeypatch.setattr(cli, "AsyncSessionLocal", session)
    monkeypatch.setattr(cli, "engine", SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr(cli.flow, "create_interactive_draft", create)
    monkeypatch.setattr(cli.runs, "enabled", lambda: False)
    return create, token


@pytest.mark.parametrize("channel_kind", ["pipe", "unix_socket"])
@pytest.mark.parametrize("delivery_lead_id", [27, 32])
def test_interactive_cli_token_goes_only_to_private_channel(
    fake_interactive_flow, capsys, channel_kind, delivery_lead_id
) -> None:
    create, token = fake_interactive_flow
    if channel_kind == "pipe":
        read_fd, write_fd = os.pipe()
        try:
            assert cli.main(_argv(write_fd, delivery_lead_id)) == 0
            delivered = os.read(read_fd, 256)
        finally:
            os.close(read_fd)
            os.close(write_fd)
    else:
        receiver, writer = socket.socketpair()
        with receiver, writer:
            assert cli.main(_argv(writer.fileno(), delivery_lead_id)) == 0
            delivered = receiver.recv(256)
    assert delivered == token.encode("ascii") + b"\n"
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "started": True,
        "run_id": 7,
        "status": "started",
        "submit": False,
        "items": 1,
    }
    create.assert_awaited_once()
    args, kwargs = create.await_args
    assert args[1] == 101
    assert (
        kwargs["delivery_lead_id"] == delivery_lead_id
        and kwargs["request_number"] == "42511"
    )


@pytest.mark.parametrize(
    "bad_option",
    ["submit", "start", "duplicate", "multiple", "missing_dl", "missing_request"],
)
def test_interactive_cli_rejects_unsafe_or_ambiguous_arguments_before_creation(
    fake_interactive_flow, capsys, bad_option
) -> None:
    create, token = fake_interactive_flow
    read_fd, write_fd = os.pipe()
    try:
        argv = _argv(write_fd)
        if bad_option in ("submit", "start"):
            argv.append(f"--{bad_option}")
        elif bad_option in ("duplicate", "multiple"):
            argv[argv.index("--stage-ids") + 1] = (
                "101,101" if bad_option == "duplicate" else "101,102"
            )
        else:
            option = (
                "--delivery-lead-id"
                if bad_option == "missing_dl"
                else "--request-number"
            )
            index = argv.index(option)
            del argv[index : index + 2]
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2
        create.assert_not_called()
        captured = capsys.readouterr()
        assert token not in captured.out + captured.err
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize(
    "bad_channel",
    [
        "stdin",
        "stdout",
        "stderr",
        "closed",
        "read_only_pipe",
        "regular_file",
        "stdout_alias",
    ],
)
def test_interactive_cli_rejects_non_private_or_unwritable_fd_before_creation(
    fake_interactive_flow, tmp_path, capsys, bad_channel
) -> None:
    create, token = fake_interactive_flow
    read_fd, write_fd = os.pipe()
    close_fds = [read_fd, write_fd]
    try:
        if bad_channel in ("stdin", "stdout", "stderr"):
            fd = {"stdin": 0, "stdout": 1, "stderr": 2}[bad_channel]
        elif bad_channel == "closed":
            fd = os.dup(write_fd)
            os.close(fd)
        elif bad_channel == "read_only_pipe":
            fd = read_fd
        elif bad_channel == "regular_file":
            fd = os.open(
                tmp_path / "not_a_private_channel", os.O_WRONLY | os.O_CREAT, 0o600
            )
            close_fds.append(fd)
        else:
            fd = os.dup(1)
            close_fds.append(fd)
        # fd=0 is refused by argument parsing; the other invalid channels
        # return a safe generic status before entering any database session.
        if fd == 0:
            with pytest.raises(SystemExit) as exc:
                cli.main(_argv(fd))
            assert exc.value.code == 2
        else:
            assert cli.main(_argv(fd)) == 2
        create.assert_not_called()
        captured = capsys.readouterr()
        assert token not in captured.out + captured.err
    finally:
        for fd in close_fds:
            os.close(fd)


@pytest.mark.parametrize("error_kind", ["not_ready", "unexpected"])
def test_interactive_cli_never_prints_sensitive_exception_details(
    fake_interactive_flow, capsys, error_kind
) -> None:
    create, token = fake_interactive_flow
    create.side_effect = (
        cli.flow.NotReady(token) if error_kind == "not_ready" else RuntimeError(token)
    )
    read_fd, write_fd = os.pipe()
    try:
        assert cli.main(_argv(write_fd)) == 1
        captured = capsys.readouterr()
        assert token not in captured.out + captured.err
        assert json.loads(captured.out)["started"] is False
        os.set_blocking(read_fd, False)
        with pytest.raises(BlockingIOError):
            os.read(read_fd, 256)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_repair_cli_binds_the_source_run_without_enabling_submit(
    fake_interactive_flow, capsys
):
    create, token = fake_interactive_flow
    read_fd, write_fd = os.pipe()
    try:
        assert cli.main([*_argv(write_fd), "--repair-draft-run-id", "42"]) == 0
        assert os.read(read_fd, 256) == token.encode("ascii") + b"\n"
        assert create.await_args.kwargs["repair_draft_run_id"] == 42
        output = capsys.readouterr()
        assert json.loads(output.out)["submit"] is False
        assert token not in output.out + output.err
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_repair_mode_cannot_be_used_with_the_webhook_start(fake_interactive_flow):
    create, _ = fake_interactive_flow
    with pytest.raises(SystemExit) as caught:
        cli.main(["--start", "--stage-ids", "101", "--repair-draft-run-id", "42"])
    assert caught.value.code == 2
    create.assert_not_called()

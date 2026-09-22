"""SEC-02 (audyt 22.09 r2): klucz z historii gita daje głośny log, nie awarię."""

from __future__ import annotations

import inspect
import logging

from app.core import config
from app.core.config import (
    LEAKED_SECRET_KEY_SHA256_PREFIXES,
    log_if_secret_key_leaked,
    secret_key_is_known_leaked,
)


def test_unknown_key_is_not_flagged(caplog):
    caplog.set_level(logging.ERROR)
    assert secret_key_is_known_leaked("a-fresh-strong-key-0123456789abcdef") is False
    assert secret_key_is_known_leaked("") is False
    assert log_if_secret_key_leaked("a-fresh-strong-key-0123456789abcdef") is False
    assert not [r for r in caplog.records if "leaked" in r.getMessage()]


def test_leaked_key_logs_error_and_never_raises(caplog, monkeypatch):
    caplog.set_level(logging.ERROR)
    key = "pretend-leaked-key"
    import hashlib

    prefix = hashlib.sha256(key.encode()).hexdigest()[:16]
    monkeypatch.setattr(
        config,
        "LEAKED_SECRET_KEY_SHA256_PREFIXES",
        LEAKED_SECRET_KEY_SHA256_PREFIXES | {prefix},
    )
    assert log_if_secret_key_leaked(key) is True
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("leaked in git history" in r.getMessage() for r in errors)
    assert all(key not in r.getMessage() for r in caplog.records), (
        "klucz nie trafia do logu"
    )


def test_real_leaked_prefix_is_registered_and_lifespan_calls_the_guard():
    assert "e76920d40b5cd73d" in LEAKED_SECRET_KEY_SHA256_PREFIXES
    from app import main

    source = inspect.getsource(main)
    assert "log_if_secret_key_leaked(settings.SECRET_KEY)" in source

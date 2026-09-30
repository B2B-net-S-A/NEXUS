"""Import FIRST: forces every DB connection of the app into read-only mode."""
import sqlalchemy.ext.asyncio as _sa

_orig = _sa.create_async_engine


def _ro_engine(url, **kw):
    ca = dict(kw.get("connect_args") or {})
    ss = dict(ca.get("server_settings") or {})
    ss["default_transaction_read_only"] = "on"
    ss["statement_timeout"] = "900000"
    ss["application_name"] = "nexus-search-research"
    ca["server_settings"] = ss
    kw["connect_args"] = ca
    kw["pool_size"] = 2
    kw["max_overflow"] = 2
    return _orig(url, **kw)


_sa.create_async_engine = _ro_engine
import logging
logging.basicConfig(level=logging.WARNING)

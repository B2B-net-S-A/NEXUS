"""Central JWT boundary for NEXUS.

Application code imports JWT primitives from this module rather than binding
directly to a third-party package. ``JWTError`` intentionally aliases
PyJWT's common base exception so callers keep one stable error contract.
"""

from collections.abc import Mapping
from typing import Any

import jwt as _pyjwt
from jwt import PyJWK
from jwt.exceptions import PyJWTError

JWTError = PyJWTError
jwt = _pyjwt


def key_from_jwk(value: Mapping[str, Any]) -> Any:
    """Convert a public JWK mapping into the key object expected by PyJWT."""
    return PyJWK.from_dict(dict(value)).key


__all__ = ["JWTError", "jwt", "key_from_jwk"]

"""Provider-neutral request/result contracts used by the AI gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Optional
from uuid import uuid4

from app.models.ai_feature import AIFeatureKey


StructuredValidator = Callable[[Any], Any]


@dataclass(frozen=True)
class FeatureRoute:
    provider: str
    model: str
    operation: str = "generate"
    timeout_seconds: float = 45.0
    max_output_tokens: int = 2048
    escalation_models: tuple[str, ...] = ()
    reservation_cost_usd: Decimal = Decimal("0")
    input_cost_per_million_usd: Decimal = Decimal("0")
    output_cost_per_million_usd: Decimal = Decimal("0")
    enabled: bool = True


@dataclass
class AIRequest:
    feature: AIFeatureKey
    messages: list[dict[str, Any]]
    request_id: str = field(default_factory=lambda: uuid4().hex)
    mode: Optional[str] = None
    user_id: Optional[int] = None
    client_id: Optional[int] = None
    subject_type: Optional[str] = None
    subject_id: Optional[int] = None
    pii: bool = True
    prompt_version: str = "v1"
    schema_version: str = "v1"
    structured_validator: Optional[StructuredValidator] = None
    cache_ttl_seconds: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIResult:
    request_id: str
    feature: AIFeatureKey
    provider: str
    model: str
    route_version: str
    content: Any
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    cached: bool = False
    escalated: bool = False


class AIError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code

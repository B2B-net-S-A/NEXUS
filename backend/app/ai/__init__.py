"""Central, versioned AI gateway for all external model calls."""

from app.ai.gateway import AIGateway, ai_gateway
from app.ai.registry import REGISTRIES, get_feature_route
from app.ai.types import AIError, AIRequest, AIResult, FeatureRoute

__all__ = [
    "AIError",
    "AIGateway",
    "AIRequest",
    "AIResult",
    "FeatureRoute",
    "REGISTRIES",
    "ai_gateway",
    "get_feature_route",
]

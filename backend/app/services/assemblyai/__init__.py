"""AssemblyAI Polish speech-to-text (EU endpoint) for call recordings."""

from app.services.assemblyai.client import (
    AssemblyAIClient,
    AssemblyAIConfig,
    AssemblyAIError,
)

__all__ = ["AssemblyAIClient", "AssemblyAIConfig", "AssemblyAIError"]

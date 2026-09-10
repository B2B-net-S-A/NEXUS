"""Bounded, integrity-checked input for an approved-version requirement map."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.cv_editor_review import editor_claims
from app.services.llm_prompts import CV_REQUIREMENT_MAP
from app.services.cv_generator_b2b.requirement_map import DEFAULT_MODEL

MAX_BYTES = 3_000_000


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=500)
    kind: Literal["must", "nice"]


class MapInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protocol_version: Literal[1] = 1
    prompt_version: str
    model: str
    document_version_id: int = Field(gt=0)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: Literal["pl", "en"]
    paragraphs: list[str] = Field(min_length=1, max_length=1000)
    requirements: list[Requirement] = Field(min_length=1, max_length=20)

    def public_payload(self):
        return {"language": self.language, "why_points": list(self.paragraphs)}


def encode_map_input(version, requirements: list[dict]) -> tuple[bytes, str]:
    content_hash = hashlib.sha256(version.content_html.encode()).hexdigest()
    if content_hash != version.content_sha256:
        raise ValueError("Approved HTML integrity mismatch")
    parsed = MapInput(
        prompt_version=str(CV_REQUIREMENT_MAP.version),
        model=DEFAULT_MODEL,
        document_version_id=version.id,
        content_sha256=content_hash,
        language=version.language,
        paragraphs=editor_claims(version.content_html),
        requirements=[Requirement.model_validate(item) for item in requirements],
    )
    raw = parsed.model_dump_json().encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("Requirement-map input exceeds limit")
    return raw, hashlib.sha256(raw).hexdigest()


def decode_map_input(raw: bytes, digest: str, version) -> MapInput:
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Requirement-map input integrity mismatch")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate requirement-map input key")
            value[key] = item
        return value

    parsed = MapInput.model_validate(json.loads(raw, object_pairs_hook=unique))
    if (
        parsed.prompt_version != str(CV_REQUIREMENT_MAP.version)
        or parsed.model != DEFAULT_MODEL
        or parsed.document_version_id != version.id
        or parsed.content_sha256 != version.content_sha256
        or parsed.language != version.language
        or hashlib.sha256(version.content_html.encode()).hexdigest()
        != parsed.content_sha256
        or parsed.paragraphs != editor_claims(version.content_html)
    ):
        raise ValueError("Requirement-map input does not match approved version")
    return parsed

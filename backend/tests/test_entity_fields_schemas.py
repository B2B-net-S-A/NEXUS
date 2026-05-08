"""Schema-level tests for custom field schema editor (#7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.entity_field import (
    FIELD_TYPE_LABELS,
    EntityType,
    FieldType,
)
from app.schemas.entity_field import (
    EntityFieldDefCreate,
    EntityFieldDefUpdate,
    FieldChoice,
)


class TestEntityType:
    def test_two_entities(self):
        assert {e.value for e in EntityType} == {"candidate", "job"}


class TestFieldTypeVocabulary:
    def test_thirteen_types(self):
        assert {f.value for f in FieldType} == {
            "text",
            "long_text",
            "number",
            "checkbox",
            "radio",
            "select",
            "multi_select",
            "date",
            "datetime",
            "file",
            "files",
            "location",
            "link",
        }

    def test_polish_labels_for_every_type(self):
        for ft in FieldType:
            assert ft in FIELD_TYPE_LABELS
            assert FIELD_TYPE_LABELS[ft]


class TestKeyConstraint:
    def test_lowercase_underscore_ok(self):
        EntityFieldDefCreate(
            entity_type=EntityType.candidate,
            key="custom_score",
            label_pl="Custom",
            field_type=FieldType.number,
        )

    def test_starting_digit_rejected(self):
        with pytest.raises(ValidationError):
            EntityFieldDefCreate(
                entity_type=EntityType.candidate,
                key="9_score",
                label_pl="x",
                field_type=FieldType.number,
            )

    def test_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            EntityFieldDefCreate(
                entity_type=EntityType.candidate,
                key="CamelCase",
                label_pl="x",
                field_type=FieldType.number,
            )

    def test_dash_rejected(self):
        with pytest.raises(ValidationError):
            EntityFieldDefCreate(
                entity_type=EntityType.candidate,
                key="custom-field",
                label_pl="x",
                field_type=FieldType.number,
            )


class TestCreatePayload:
    def test_minimal_text(self):
        payload = EntityFieldDefCreate(
            entity_type=EntityType.candidate,
            key="lin",
            label_pl="LinkedIn URL",
            field_type=FieldType.link,
        )
        assert payload.section == "middle"
        assert payload.required is False
        assert payload.options == {}

    def test_select_with_choices_in_options(self):
        payload = EntityFieldDefCreate(
            entity_type=EntityType.job,
            key="priority",
            label_pl="Priorytet",
            field_type=FieldType.select,
            options={
                "choices": [
                    {"value": "high", "label": "Wysoki"},
                    {"value": "low", "label": "Niski"},
                ]
            },
        )
        assert payload.field_type is FieldType.select
        assert len(payload.options["choices"]) == 2

    def test_label_max_length(self):
        with pytest.raises(ValidationError):
            EntityFieldDefCreate(
                entity_type=EntityType.candidate,
                key="x",
                label_pl="x" * 201,
                field_type=FieldType.text,
            )


class TestUpdatePayload:
    def test_partial_section_change(self):
        u = EntityFieldDefUpdate(section="left")
        assert u.section == "left"
        assert u.label_pl is None

    def test_partial_archive(self):
        u = EntityFieldDefUpdate(archived=True)
        assert u.archived is True

    def test_negative_ordinal_rejected(self):
        with pytest.raises(ValidationError):
            EntityFieldDefUpdate(ordinal=-1)


class TestFieldChoice:
    def test_round_trip(self):
        c = FieldChoice(value="high", label="Wysoki")
        assert c.value == "high"

    def test_empty_value_rejected(self):
        with pytest.raises(ValidationError):
            FieldChoice(value="", label="x")

from types import SimpleNamespace

import pytest

from app.api import ai_writer


def test_template_does_not_invent_facts_for_title_only():
    result = ai_writer._generate_mock(
        ai_writer.GenerateJobRequest(title="Python Developer")
    )
    assert result.title == "Python Developer"
    assert result.description == "Stanowisko: Python Developer."
    assert (
        result.requirements
        == result.benefits
        == result.nice_to_have
        == result.salary_range_suggestion
        == ""
    )


@pytest.mark.parametrize("seniority", ["junior", "senior", "lead"])
def test_seniority_does_not_imply_years_or_skills(seniority):
    result = ai_writer._generate_mock(
        ai_writer.GenerateJobRequest(
            title="Developer", seniority=seniority, skills=["Python lub Java"]
        )
    )
    assert result.requirements == "- Python lub Java"
    assert "lat" not in result.description
    assert result.salary_range_suggestion == ""


@pytest.mark.asyncio
async def test_legacy_writer_preserves_requirements_without_defaults():
    result = await ai_writer.generate_job_description(
        ai_writer.JobDescriptionRequest(
            title="Developer", requirements="Python lub Java", seniority="lead"
        ),
        current_user=SimpleNamespace(),
        db=None,
    )
    assert (
        result.description
        == "## Lead / Tech Lead Developer\n\n## Wymagania\n\nPython lub Java"
    )


@pytest.mark.asyncio
async def test_provider_cannot_replace_criteria_or_inject_salary(monkeypatch):
    import app.services.claude_client as claude_client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def respond(**kwargs):
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    text='{"description":"Szkic", "requirements":"Kubernetes", "benefits":"Car", "nice_to_have":"Java", "salary_range_suggestion":"30000"}'
                )
            ]
        )

    monkeypatch.setattr(claude_client, "call_claude", respond)
    result = await ai_writer._generate_with_claude(
        ai_writer.GenerateJobRequest(title="Developer", skills=["Python"])
    )
    assert result.requirements == "- Python"
    assert (
        result.benefits == result.nice_to_have == result.salary_range_suggestion == ""
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "[]",
        "null",
        '{"description":null}',
        '{"description":42}',
        '{"description":"  "}',
    ],
)
async def test_unusable_provider_description_is_not_a_successful_draft(
    monkeypatch, payload
):
    import app.services.claude_client as claude_client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(
        claude_client,
        "call_claude",
        lambda **kwargs: SimpleNamespace(content=[SimpleNamespace(text=payload)]),
    )
    with pytest.raises(ValueError, match="no usable job description"):
        await ai_writer._generate_with_claude(
            ai_writer.GenerateJobRequest(title="Developer")
        )


@pytest.mark.asyncio
async def test_provider_is_only_asked_for_consumed_description(monkeypatch):
    import json
    import app.services.claude_client as claude_client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def respond(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        schema = json.loads(prompt[prompt.rindex("{") :])
        assert set(schema) == {"description"}
        return SimpleNamespace(
            content=[SimpleNamespace(text='{"description":"  Developer Python  "}')]
        )

    monkeypatch.setattr(claude_client, "call_claude", respond)
    result = await ai_writer._generate_with_claude(
        ai_writer.GenerateJobRequest(title="Developer", skills=["Python"])
    )
    assert result.description == "Developer Python"
    assert result.requirements == "- Python"
    assert result.salary_range_suggestion == ""

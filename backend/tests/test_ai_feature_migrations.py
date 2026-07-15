"""Focused contracts for migrated production AI features."""

from types import SimpleNamespace

import pytest

from app.ai import AIError
from app.api import ai_writer
from app.api.ai_writer import GenerateJobRequest, GeneratedSalary
from app.services.b2b_contract_generator import uop_check


@pytest.mark.asyncio
async def test_job_writer_preserves_structured_hourly_salary(monkeypatch):
    salary = GeneratedSalary(
        min=140,
        max=170,
        currency="PLN",
        period="hour",
        employment_type="b2b",
    )

    async def call(request):  # type: ignore[no-untyped-def]
        content = request.structured_validator(
            {
                "title": "Senior Python Developer",
                "description": "Rozwój platformy klienta w doświadczonym zespole.",
                "requirements": "- Python\n- FastAPI\n- SQL\n- Git\n- REST\n- Angielski B2",
                "nice_to_have": "- AWS\n- Docker\n- Kubernetes",
                "benefits": "- Praca zdalna",
                "salary": salary.model_dump(),
                "generation_source": "ai",
                "salary_range_suggestion": "",
            }
        )
        return SimpleNamespace(content=content)

    monkeypatch.setattr(ai_writer.ai_gateway, "call", call)
    result = await ai_writer._generate_with_claude(
        GenerateJobRequest(
            title="Python Developer",
            benefits=["Praca zdalna"],
            salary=salary,
        ),
        user_id=7,
    )

    assert result.salary == salary
    assert result.salary.period == "hour"
    assert result.generation_source == "ai"
    assert result.salary_range_suggestion == "140–170 PLN / hour (b2b)"


@pytest.mark.asyncio
async def test_job_writer_rejects_invented_salary(monkeypatch):
    async def call(request):  # type: ignore[no-untyped-def]
        request.structured_validator(
            {
                "title": "Developer",
                "description": "Opis stanowiska oparty o przekazane dane.",
                "requirements": "- Python",
                "nice_to_have": "",
                "benefits": "",
                "salary": {
                    "min": 100,
                    "max": 120,
                    "currency": "PLN",
                    "period": "hour",
                    "employment_type": "b2b",
                },
                "generation_source": "ai",
                "salary_range_suggestion": "",
            }
        )

    monkeypatch.setattr(ai_writer.ai_gateway, "call", call)
    with pytest.raises(ValueError, match="invented salary"):
        await ai_writer._generate_with_claude(
            GenerateJobRequest(title="Developer"), user_id=7
        )


@pytest.mark.asyncio
async def test_uop_rules_survive_provider_failure(monkeypatch):
    async def fail(_request):  # type: ignore[no-untyped-def]
        raise AIError("provider_error", "unavailable")

    monkeypatch.setattr(uop_check.ai_gateway, "call", fail)
    text = "Praca od 9:00 do 17:00 zgodnie z poleceniami przełożonego."
    result = await uop_check.check_employment_hallmarks(text, user_id=7)

    assert result["analysis_mode"] == "rules_only"
    assert result["requires_confirmation"] is True
    assert result["input_hash"]
    assert {issue["phrase"].casefold() for issue in result["issues"]} >= {
        "przełożonego",
    }


@pytest.mark.asyncio
async def test_uop_rejects_hallucinated_quote(monkeypatch):
    async def call(request):  # type: ignore[no-untyped-def]
        request.structured_validator(
            {
                "issues": [
                    {
                        "phrase": "urlop pracowniczy",
                        "why": "Ryzyko.",
                        "suggestion": "Przerwa w usługach.",
                    }
                ],
                "rewritten": "Samodzielne świadczenie usług.",
                "summary": "Wymaga korekty.",
            }
        )

    monkeypatch.setattr(uop_check.ai_gateway, "call", call)
    with pytest.raises(ValueError, match="not present"):
        await uop_check.check_employment_hallmarks("Samodzielna realizacja usługi.")

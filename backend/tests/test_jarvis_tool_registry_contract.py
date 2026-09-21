"""Kontrakt rejestru narzędzi Jarvisa — to, co trzyma asystenta w ryzach.

- Każde narzędzie woła trasę, która ISTNIEJE (inaczej model dostaje 404 i
  wymyśla odpowiedź).
- Narzędzie ``read`` woła wyłącznie trasę uznaną za odczyt przez tę samą
  regułę, która rządzi sekcjami i impersonacją (``is_read_only_http_request``).
- Żadne narzędzie wykonywalne nie sięga po operacje krytyczne: usuwanie,
  wypowiedzenia, podpisy, stawki, maile, administrację. Te idą przez
  ``open_screen`` — klika człowiek.
- Ekrany z ``open_screen`` istnieją we froncie.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.services.jarvis import tools as jarvis_tools
from app.services.jarvis.tools import ALL_TOOLS, SCREENS, TOOLS_BY_NAME, tools_for_user
from app.services.request_semantics import is_read_only_http_request
from app.services.section_permissions import ProductSection
from tests._route_introspection import iter_api_routes

REPO = Path(__file__).resolve().parents[2]
FRONTEND_APP = REPO / "frontend" / "src" / "app"

# Fragmenty ścieżek, których ŻADNE narzędzie wykonywalne nie może dotknąć.
_FORBIDDEN_FRAGMENTS = (
    "/api/admin",
    "/terminate",
    "/void",
    "/activate",
    "/reopen",
    "confirm-fully-signed",
    "/signing",
    "/autenti",
    "/emails",
    "/send",
    "/rates",
    "/client-rate",
    "/merge",
    "/b2b-generator",
    "/cv-generator",
    "/settings",
    "/auth",
)


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _registered_routes() -> set[tuple[str, str]]:
    from app.main import app

    routes: set[tuple[str, str]] = set()
    for path, route in iter_api_routes(app):
        for method in route.methods or ():
            routes.add((method.upper(), path))
    return routes


def test_tool_names_are_unique_and_described():
    names = [tool.name for tool in ALL_TOOLS]
    assert len(names) == len(set(names))
    for tool in ALL_TOOLS:
        assert re.fullmatch(r"[a-z][a-z0-9_]{2,63}", tool.name), tool.name
        assert len(tool.description) >= 30, tool.name
        assert tool.label, tool.name
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema.get("additionalProperties") is False, tool.name
        props = tool.input_schema.get("properties") or {}
        for required in tool.input_schema.get("required") or []:
            assert required in props, (tool.name, required)


@pytest.mark.parametrize(
    "tool", [t for t in ALL_TOOLS if t.tier != "link"], ids=lambda t: t.name
)
def test_every_tool_targets_a_registered_route(tool):
    assert tool.method and tool.path
    assert (tool.method, tool.path) in _registered_routes(), (
        f"{tool.name}: {tool.method} {tool.path}"
    )


@pytest.mark.parametrize(
    "tool", [t for t in ALL_TOOLS if t.tier == "read"], ids=lambda t: t.name
)
def test_read_tools_hit_read_only_routes(tool):
    assert is_read_only_http_request(tool.method, _concrete(tool.path)), tool.name


@pytest.mark.parametrize(
    "tool", [t for t in ALL_TOOLS if t.tier == "write"], ids=lambda t: t.name
)
def test_write_tools_are_reversible_and_have_a_card(tool):
    assert tool.method != "DELETE", tool.name
    assert not is_read_only_http_request(tool.method, _concrete(tool.path)), tool.name
    assert tool.preview is not None and tool.done != "Gotowe.", tool.name
    assert tool.description.startswith("PROPONUJE"), tool.name


@pytest.mark.parametrize(
    "tool", [t for t in ALL_TOOLS if t.tier != "link"], ids=lambda t: t.name
)
def test_no_executable_tool_reaches_a_critical_operation(tool):
    for fragment in _FORBIDDEN_FRAGMENTS:
        assert fragment not in tool.path, f"{tool.name} dotyka {fragment}"


def test_build_matches_the_declared_route():
    """``build`` musi wołać trasę z deklaracji — inaczej test wyżej mierzy fikcję."""
    samples = {
        "candidate_id": 11,
        "job_id": 22,
        "client_id": 33,
        "alert_id": 44,
        "pool_id": 55,
        "id_or_slug": "zamowienia",
        "stage_def_id": 66,
        "stage_name": "Zweryfikowany",
        "candidate_ids": [1, 2],
        "content": "treść",
        "title": "Rozmowa",
        "start_time": "2026-09-22T10:00:00+02:00",
        "text": "Senior Java",
        "query": "java",
        "year": 2026,
        "month": 9,
    }
    for tool in ALL_TOOLS:
        if tool.tier == "link":
            continue
        props = tool.input_schema.get("properties") or {}
        args = {k: v for k, v in samples.items() if k in props}
        spec = tool.build(args)
        assert spec.method == tool.method, tool.name
        pattern = "^" + re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(tool.path)) + "$"
        assert re.match(pattern, spec.path), (tool.name, spec.path)


def test_add_candidates_is_attributed_to_jarvis():
    spec = TOOLS_BY_NAME["add_candidates_to_job"].build(
        {"job_id": 1, "candidate_ids": [3]}
    )
    assert spec.json["source"] == "jarvis"


def test_acknowledge_eligibility_is_never_offered_to_the_model():
    """„Przenieś mimo ostrzeżenia” ustawia wyłącznie serwer po prawdziwym 409."""
    props = TOOLS_BY_NAME["move_candidate_stage"].input_schema["properties"]
    assert "acknowledge_eligibility" not in props


def test_calendar_tool_never_invites_other_people():
    props = TOOLS_BY_NAME["create_calendar_event"].input_schema["properties"]
    assert "attendees" not in props
    assert "teams_link" not in props


@pytest.mark.parametrize("screen", sorted(SCREENS))
def test_open_screen_targets_existing_frontend_pages(screen):
    template, _label = SCREENS[screen]
    path = template.split("?")[0].replace("{id}", "[id]").strip("/")
    directory = FRONTEND_APP / path
    assert directory.is_dir(), f"{screen}: brak katalogu {directory}"


def test_open_screen_rejects_unknown_screens_and_requires_ids():
    with pytest.raises(ValueError):
        jarvis_tools.build_screen_link({"screen": "admin_panel", "reason": "x"})
    with pytest.raises(ValueError):
        jarvis_tools.build_screen_link({"screen": "candidate", "reason": "x"})
    assert (
        jarvis_tools.build_screen_link({"screen": "calendar", "reason": "x"})["href"]
        == "/calendar"
    )


def test_tool_filter_follows_section_access():
    none = {section: 0 for section in ProductSection}
    offered = {tool.name for tool in tools_for_user(none)}
    # Bez żadnej sekcji zostają narzędzia bez sekcji: Pomoc, powiadomienia, link.
    assert "open_screen" in offered and "search_help" in offered
    assert "search_candidates" not in offered

    read_only = {**none, ProductSection.pipeline: 1}
    offered = {tool.name for tool in tools_for_user(read_only)}
    assert "get_job_board" in offered
    assert "move_candidate_stage" not in offered, (
        "zapis wymaga sekcji na poziomie write"
    )

    write = {**none, ProductSection.pipeline: 2}
    assert "move_candidate_stage" in {tool.name for tool in tools_for_user(write)}


def test_render_result_truncates_with_a_visible_marker():
    text = jarvis_tools.render_result({"x": "a" * 20000})
    assert len(text) < 6200
    assert text.endswith("zawęź zapytanie]")


def test_router_module_has_no_future_annotations():
    """slowapi #579: PEP 563 zamienia guardy `Annotated` w parametry QUERY."""
    source = (REPO / "backend" / "app" / "api" / "jarvis.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            pytest.fail(
                "app/api/jarvis.py nie może mieć `from __future__ import annotations`"
            )


def test_invalidation_keys_exist_in_the_frontend():
    """Klucz odświeżenia, którego front nie używa, to cicha nieaktualność ekranu
    po akcji — karta mówi „wykonane”, a lista pod spodem stoi w miejscu."""
    sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (REPO / "frontend" / "src").rglob("*.ts*")
        if "__tests__" not in path.parts
    )
    for tool in ALL_TOOLS:
        for key in tool.invalidates:
            assert f'"{key[0]}"' in sources, (
                f"{tool.name}: klucz {key[0]!r} nie występuje we froncie"
            )


def test_long_procedure_returns_matching_sections_not_a_teaser():
    """Test na produkcji 21.09: na „jak dodać zamówienie z PDF-a” Jarvis widział
    tylko zajawkę 40-kilobajtowej instrukcji (ucięcie do 400 znaków)."""
    from app.services.jarvis.tools import shape_procedure

    filler = "\n".join(f"## Sekcja {i}\n" + ("lorem ipsum " * 80) for i in range(30))
    content = (
        filler
        + "\n## Dodawanie zamówienia z PDF-a\nKrok 1: wgraj plik PDF.\nKrok 2: sprawdź pola.\n"
    )
    shaped = shape_procedure(
        {"id": 1, "slug": "x", "title": "T", "content": content}, "pdf"
    )
    assert shaped["matched_sections"][0]["heading"] == "Dodawanie zamówienia z PDF-a"
    assert "Krok 2: sprawdź pola." in shaped["matched_sections"][0]["content"]
    assert "Sekcja 0" in shaped["all_headings"]

    short = shape_procedure({"id": 1, "content": "krótka treść"}, None)
    assert short["content"] == "krótka treść"


def test_long_text_fields_are_not_cut_to_a_teaser():
    from app.services.jarvis.tools import trim

    assert len(trim({"summary": "a" * 1200})["summary"]) == 1200

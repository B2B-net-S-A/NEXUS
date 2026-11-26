"""`scripts/impact_map.py`: inne miejsca z tą samą informacją co zmiana z gałęzi."""

import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location(
    "impact_map", Path(__file__).resolve().parents[2] / "scripts/impact_map.py"
)
im = importlib.util.module_from_spec(spec)
sys.modules["impact_map"] = im
spec.loader.exec_module(im)

DIFF = """\
diff --git a/backend/app/schemas/candidate.py b/backend/app/schemas/candidate.py
--- a/backend/app/schemas/candidate.py
+++ b/backend/app/schemas/candidate.py
@@ -1,2 +1,3 @@
+    rate_from: Decimal | None = None
+    id: int
diff --git a/backend/app/api/candidates.py b/backend/app/api/candidates.py
--- a/backend/app/api/candidates.py
+++ b/backend/app/api/candidates.py
@@ -1 +1,2 @@
+@router.get("/api/candidates/{cid}/rate-history")
diff --git a/frontend/src/lib/api/candidates.ts b/frontend/src/lib/api/candidates.ts
--- a/frontend/src/lib/api/candidates.ts
+++ b/frontend/src/lib/api/candidates.ts
@@ -1 +1,2 @@
+  rateFromNote?: string;
diff --git a/frontend/src/components/v2/person/RateBadge.tsx b/frontend/src/components/v2/person/RateBadge.tsx
--- /dev/null
+++ b/frontend/src/components/v2/person/RateBadge.tsx
@@ -0,0 +1 @@
+export function RateBadge() {}
"""


def _names(symbols):
    return {(s.name, s.kind) for s in symbols}


def test_symbols_from_diff_fields_endpoints_components():
    syms = im.symbols_from_diff(im.changed_lines(DIFF))
    assert _names(syms) == {
        ("rate_from", "pole"),
        ("rateFromNote", "pole"),
        ("/api/candidates", "endpoint"),
        ("RateBadge", "komponent"),
    }  # `id` pominięte jako nazwa ogólna


def test_rate_from_places_panel_profile_pdf_jarvis_export():
    hits = {
        "rate_from": [
            "backend/app/schemas/candidate.py",  # zmieniony w diffie
            "frontend/src/components/v2/person/PersonPanel.tsx",
            "frontend/src/app/(app)/candidates/[id]/page.tsx",
            "backend/app/services/cv_pdf_render.py",
            "backend/app/services/jarvis/tools.py",
            "backend/app/api/import_export.py",
            "backend/app/data/screen_guides/candidate.py",
            "backend/app/services/candidate_rate_from.py",  # logika, nie miejsce dla ludzi
            "frontend/src/app/preview/candidate-profile/page.tsx",  # harness
            "frontend/src/components/v2/__tests__/x.test.tsx",
        ]
    }
    places = im.places_for(
        [im.Symbol("rate_from", "pole")],
        {"backend/app/schemas/candidate.py"},
        search=lambda s: hits.get(s.name, []),
    )
    assert [p.label for p in places] == [
        "Jarvis",
        "dokument/mail",
        "ekran /candidates/[id]",
        "eksport",
        "komponent PersonPanel",
        "przewodnik ekranu",
    ]
    table = im.render(places)
    assert table.splitlines()[0] == "| Miejsce | Decyzja |"
    assert "| Jarvis — `rate_from · backend/app/services/jarvis/tools.py` |  |" in table


def test_field_without_other_uses_gives_empty_list():
    places = im.places_for(
        [im.Symbol("brand_new_field", "pole")],
        {"backend/app/schemas/candidate.py"},
        search=lambda s: ["backend/app/schemas/candidate.py"],
    )
    assert places == []
    assert "(brak innych miejsc)" in im.render(places)


def test_no_symbols_in_docs_only_diff():
    diff = "+++ b/docs/x.md\n+    rate_from: tekst\n"
    assert im.symbols_from_diff(im.changed_lines(diff)) == []

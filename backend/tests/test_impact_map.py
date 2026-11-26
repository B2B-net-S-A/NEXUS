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


# PR #4058: nowy typ `CvHighlightProposal` z polami `text`, `source`, `company`… i opcja
# `timeout:` w `candidateStageCvApi` dały 2797 miejsc, z których żadne nie czytało
# nowej informacji. Liczby trafień z pomiaru na mainie 26.11.2026.
PR4058_DIFF = (Path(__file__).parent / "data/impact_map/pr4058-api-ts.diff").read_text()
PR4058_HITS = {
    "text": 1937,
    "source": 322,
    "company": 157,
    "token": 122,
    "proposal": 63,
    "quote": 62,
    "verified": 58,
    "issue": 38,
    "timeout": 27,
}


def _fake_hits(counts):
    return lambda s: [f"frontend/src/components/v2/x/{s.name}{i}.tsx" for i in range(counts.get(s.name, 0))]


def test_pr4058_generic_fields_and_object_options_are_not_symbols():
    syms = im.symbols_from_diff(im.changed_lines(PR4058_DIFF))
    assert _names(syms) == {
        ("highlight_proposals", "pole"),
        ("highlight_source_sha", "pole"),
        ("highlight_rejected", "pole"),
        ("highlight_reject", "pole"),
        ("proposal", "pole"),
    }  # bez `timeout` i `refreshPage1Highlight`: to właściwości obiektu `candidateStageCvApi`


def test_pr4058_gives_one_collective_row_not_2797():
    files = im.changed_lines(PR4058_DIFF)
    places = im.places_for(im.symbols_from_diff(files), set(files), search=_fake_hits(PR4058_HITS))
    assert [p.key for p in places] == ["proposal · *"]
    assert "| za ogólne (miejsc: 63) — decyzja zbiorcza — `proposal · *` |  |" in im.render(places)


def test_too_broad_threshold_is_per_symbol():
    at_limit = im.places_for(
        [im.Symbol("rate_from", "pole")], set(), search=_fake_hits({"rate_from": im.TOO_BROAD})
    )
    over = im.places_for(
        [im.Symbol("rate_from", "pole"), im.Symbol("page1_extras", "pole")],
        set(),
        search=_fake_hits({"rate_from": im.TOO_BROAD + 1, "page1_extras": 3}),
    )
    assert len(at_limit) == im.TOO_BROAD
    assert [p.key for p in over] == [
        "page1_extras · frontend/src/components/v2/x/page1_extras0.tsx",
        "page1_extras · frontend/src/components/v2/x/page1_extras1.tsx",
        "page1_extras · frontend/src/components/v2/x/page1_extras2.tsx",
        "rate_from · *",
    ]


def test_ts_field_counts_only_in_type_declaration():
    diff = """\
+++ b/frontend/src/lib/api.ts
@@ -10,3 +10,9 @@ export interface CvPage1Extras {
+  highlight_proposals?: CvHighlightProposal[] | null;
 }
 export const cvApi = {
+  refresh: (id: number) =>
+    api.post(`/x/${id}`, undefined, { timeout: SLOW_MS }),
+  create: (data: {
+    duplicateOfJobId?: number | null;
+    retryLimit: number;
+  }) => api.post("/x", data),
+    page1_extras: extras,
@@ -90,2 +96,3 @@ export const cvApi = {
+    timeout: SLOW_MS,
+export type Mode = {
+  rate_from_note: string;
"""
    assert {s.name for s in im.symbols_from_diff(im.changed_lines(diff))} == {
        "highlight_proposals",  # w `interface` z nagłówka hunka
        "duplicateOfJobId",  # typ w sygnaturze metody: `?:`
        "retryLimit",  # typ w sygnaturze metody: `;` na końcu
        "rate_from_note",  # nowa deklaracja `type` w hunku
    }  # bez `refresh`, `page1_extras: extras,` i `timeout` — przypisania w obiekcie

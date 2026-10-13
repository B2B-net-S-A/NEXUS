# Zwijanie CV i wymagań w panelu osoby — raport

Gałąź `claude/cv-project-expand-collapse-0094a0`, 13.10.2026. Makiety:
https://claude.ai/artifact/3DY3nu6cNPP2d93Bx8wL6k. Tylko front — bez API i migracji.

## Skąd zmiana

Rekruter poprosił o zwijanie CV i „informacji o projekcie” w rozwiniętym panelu osoby, tak żeby reszta się
rozszerzała. Przed zmianą (kod i zrzut rekrutera, monitor ok. 1730 × 815):

- trzy stałe kolumny: CV ok. 770 px, „Wymagania / Po ludzku” 440 px, panel 520 px;
- jedyny przycisk układu, „Zwiń” w nagłówku panelu, chowa naraz CV i wymagania (wąski dok 380 px);
- na laptopie 1280 × 720 CV, „Wymagania” i „Po ludzku” są zakładkami — czytając CV, nie widać wymagań.

## Decyzje Artura (13.10.2026: „tak na wszystkie D1–D4”)

| | Decyzja |
|---|---|
| D1 | Wariant A: zwijane kolumny; zwinięte wymagania zostają paskiem nad CV |
| D2 | Po zwinięciu CV wymagania i panel dzielą ekran po połowie |
| D3 | Na laptopie pasek krytycznych wymagań stoi nad CV także przy otwartych wymaganiach |
| D4 | Układ pamiętany per osoba w przeglądarce |

Jedno odejście od makiety A4: przy zwiniętym CV informacje o rekrutacji to zawsze jedna przewijana kolumna (jak
dotąd kolumna 440 px na monitorze), także na laptopie — zamiast zakładek „Wymagania | Po ludzku”. Mniej stanów
i nic nie chowa się za zakładką w czasie rozmowy.

## Co się zmieniło

- `lib/person-preview-layout.ts` — pamięć układu per osoba (`nexus:person-preview-layout:<id>`), odporna na
  zepsuty wpis i zablokowaną pamięć przeglądarki.
- `person/PersonPanelSide.tsx` — dostawca strefy trzyma układ; `usePersonPreviewCollapse()` (tylko w powłoce i od
  1024 px okna); `PersonPanelColumn` liczy szerokość prawej kolumny (460/520 px, po zwinięciu CV połowa bez listwy,
  przy obu zwiniętych reszta obok dwóch listew). Powłoka i harness `/preview/screening-form` używają tej samej kolumny.
- `champion/use-job-requirements.ts` — wspólne liczenie wymagań i warunków; `JobRequirementsSummary` z niego korzysta
  bez zmiany wyglądu.
- `champion/JobRequirementsStrip.tsx` — pasek: krytyczne (albo cztery „Musi mieć” + „+N”), „Szukaj w CV” z chipa,
  warunki w jednej linii, „Wszystkie wymagania”; szkielet, awaria z „Ponów”, pusty stan.
- `screening-form/CandidatePreviewPane.tsx` — prop `collapsible`, „Zwiń CV” / „Zwiń wymagania”, listwy, pasek;
  raz pokazane części zostają zamontowane (bez drugiego pobrania CV), CV zwinięte od startu nie pobiera pliku.
- `collapsible` włączone w `PersonSidePreview` (wspólny podgląd, Rozmowy) i `ScreeningWorkbench`.
- Inwentarz `recruitment-feature-inventory.json`: `preview.collapse-cv`, `preview.collapse-requirements`,
  `preview.requirements-strip`, `preview.layout-memory`.
- Reguła: `docs/claude/rekrutacja-tablica/duzy-podglad-po-lewej-stronie-panelu-osoby.md`.

## Pomiar po zmianie (harness `/preview/job-detail`, Playwright)

| Okno | Układ | Strefa podglądu | Kolumna panelu | CV / informacje |
|---|---|---|---|---|
| 1280 × 720 | domyślny | 819 | 460 | CV 818 (zakładki + pasek) |
| 1280 × 720 | zwinięte CV | 662 | 618 | informacje 617 |
| 1280 × 720 | oba zwinięte | 88 | 1191 | — |
| 1730 × 815 | domyślny | 1209 | 520 | CV 768, wymagania 440 |
| 1730 × 815 | zwinięte wymagania | 1209 | 520 | CV 1208 |
| 1730 × 815 | zwinięte CV | 887 | 843 | informacje 842 |

Bez przewijania strony w bok w żadnym układzie.

## Sprawdzone

- vitest (wątki, bez równoległości plików): `person-preview-layout`, `PersonPanelSide`, `PersonPanelShell`,
  `JobRequirementsStrip`, `JobRequirementsSummary`, `CandidatePreviewPane`, `ScreeningWorkbench`,
  `PersonWorkbenchTabs`, `recruitment-feature-parity`, `heavy-bundle-boundaries`, `responsive-guards`.
- `tsc --noEmit`, eslint na zmienionych plikach, `build_claude_index.py --check`.
- e2e `responsive-preview.spec.ts` → „panel osoby — duży podgląd…” (10 scenariuszy, w tym dwa nowe:
  zwinięte CV po połowie i pamiętane po przeładowaniu; zwinięte wymagania dają CV całą strefę przy 1730 px)
  na lokalnym `next dev`.

## Przegląd kodu (13.10.2026)

Dwa problemy znalezione i naprawione przed PR-em, każdy z testem, który najpierw padał:

- historia osoby otwarta przed zwinięciem CV zostawała otwarta, więc „Pokaż” z profilu przed telefonem nic nie
  zmieniał — zwinięcie CV zamyka teraz historię w każdym podglądzie;
- układ jest wspólny dla sekcji panelu, więc zwinięcie wymagań w zakładce CV montowało i pobierało CV w ukrytym
  podglądzie Screeningu — podgląd ukrytej sekcji nie montuje nic nowego, dopóki nie wróci.

## Niepotwierdzone

- Zalogowana produkcja z prawdziwym CV (PDF i Word) — do przeklikania po wdrożeniu.

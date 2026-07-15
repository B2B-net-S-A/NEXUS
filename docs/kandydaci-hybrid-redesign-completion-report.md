# Kandydaci — redesign hybrydowy listy (1a + panel)

> Implementacja designu `Kandydaci.dc.html` (Claude Design) na produkcyjnej liście
> kandydatów NEXUS. Wybór użytkownika: **hybryda (rozwijana tabela 1a + dokowany
> panel 1b)**, dostarczona jako **nowy, opt-in tryb widoku „Split"** obok
> istniejących Tabela/Kafelki. Token-first (bez hardcoded kolorów).

## Co i dlaczego

Mockup proponował dwa podejścia do „odchudzenia" gęstej listy kandydatów:
- **1a** — czysta tabela, gęsty tekst (AI/notatki) schowany pod rozwijaniem wiersza,
- **1b** — lista + dokowany panel profilu po prawej.

Użytkownik wybrał **hybrydę** obu. Żeby nie ruszać dojrzałej, wirtualizowanej
tabeli (3,5 tys. linii) i nie ryzykować regresji, hybryda została dodana jako
**trzeci tryb widoku** — istniejące `list`/`tiles` są nietknięte.

## Co powstało

### Fundament (współdzielony, token-first)
- `stageTone(stage)` + `StagePill` — kolorowy pill etapu z kropką dla **wszystkich
  13 etapów** pipeline'u, mapowany na semantyczne tony DS Badge:
  `cv_sent/verified/prep_call → info`, `screening/negotiation → warning`,
  `interview/client_interview → soft` (indygo/primary), `acceptance/onboarding/hired
  → success`, `rejected → danger`, `new/withdrawn → neutral`.
  (Zastępuje poprzedni `stageBadgeClass`, który kolorował tylko etapy terminalne.)
- `avatarTone(seed)` — deterministyczny, tokenowy tint awatara.

### Komponenty prezentacyjne (reużywalne — podgląd i produkcja)
- `CandidateDetailPanel` (1b) — panel profilu: tożsamość, akcje (tel/e-mail/CV),
  headline, umiejętności, siatka szczegółów, karta procesu rekrutacyjnego,
  ostatnia notatka, powód odrzucenia.
- `CandidateRowDetail` (1a) — blok rozwijany w wierszu: headline + siatka pól +
  wszystkie umiejętności + notatka + karta odrzucenia.

### Produkcja
- `CandidatesSplitView` — trzeci tryb widoku: po lewej skanowalna lista z
  rozwijaniem wierszy (1a), po prawej dokowany panel (1b, `xl:`). Zasilany tymi
  samymi danymi co tabela/kafelki (`toCandidateDetail` mapuje `Candidate` →
  `CandidateDetailData`). Bulk-checkboxy spięte z selekcją rodzica; „Pełny profil"
  otwiera istniejący QuickView.
- Wpięcie w `CandidatesListV2`: nowy przełącznik widoku (ikona `PanelRight`),
  gałąź renderująca `CandidatesSplitView`, `splitRows` z mapowania, oraz
  `include_*` flagi włączone dla trybu split (jak dla kafelków). **Zero zmian w
  ścieżkach `list`/`tiles`.**

### Podgląd (auth-free harness)
- `/preview/candidates` — pełna hybryda (nagłówek + toolbar + rozwijana tabela +
  panel) na danych z mockupu.
- `/preview/candidates-split` — **produkcyjny** `CandidatesSplitView` na tych samych
  danych (weryfikacja realnego komponentu bez JWT).

## Mapowanie token-first (zieleń+krem mockupu → tokeny NEXUS)
| Mockup | Token NEXUS |
|---|---|
| zieleń `#178a53` (pozytywne etapy, stawka) | `--success` |
| akcent interaktywny / zaznaczenie | `--primary` (indygo motywu) |
| krem `#eceae5`/`#faf9f7` | `--muted` / `--card` |
| 7 kolorów etapów | `success`/`warning`/`info`/`soft`/`destructive`/`neutral` |

Dark-mode działa automatycznie. Repo ma też `[data-theme="green"]`, gdyby chcieć
globalnie zielony primary jak w mockupie — bez hardcode.

## Pliki
**Nowe:** `components/v2/candidates/{StagePill,CandidateDetailPanel,CandidateRowDetail,CandidatesSplitView,candidate-detail-vm}.tsx/.ts`,
`components/candidates/preview/{CandidateListHybridPreview,CandidateSplitPreview,hybrid-fixtures}.tsx/.ts`,
`app/preview/candidates-split/page.tsx`.
**Zmienione:** `components/v2/pages/{CandidatesListV2,candidate-list-helpers,candidate-list-query}.tsx/.ts`,
`app/preview/candidates/page.tsx`, `lib/url-filters.ts`, `store/ui.ts`.

## Weryfikacja
- `tsc --noEmit` — czysto (cały projekt).
- `npm run lint:tokens` (guard token-first dla komponentów kandydata) — **passed (32 plików)**.
- ESLint — czysto (0 błędów, 0 ostrzeżeń po poprawce zależności `useMemo`).
- Chrome (in-app, 1440×900): podgląd hybrydy — rozwijanie 1a + panel 1b, light+dark;
  produkcyjny `CandidatesSplitView` — auto-select pierwszego, klik → panel, chevron
  → rozwinięcie z kartą odrzucenia.

## Znane ograniczenia / follow-up
- Panel produkcyjny pokazuje **ostatnią notatkę** zamiast streszczenia AI (list
  payload nie zawiera `ai_summary` — pobierane dopiero w QuickView). „Pełny profil"
  otwiera QuickView z pełnymi danymi.
- Panel widoczny od `xl` (≥1280px); poniżej lista pełnej szerokości + rozwijanie 1a
  jako nośnik szczegółów.
- Split tłumaczy się na `tiles` na mobile (spójne z istniejącym zachowaniem).

## Świadomie NIE zrobione (poza zakresem)
- Rozwijanie wierszy (1a) w domyślnej **wirtualizowanej** tabeli — użytkownik wybrał
  dostarczenie hybrydy jako osobny tryb (bezpieczniejsze, zero regresji).
- Wirtualizacja listy w trybie split (renderuje stronę wyników, ~25–50 wierszy).

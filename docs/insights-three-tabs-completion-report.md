# Insights — trzy zakładki w układzie DynaReportera

Data: 2026-09-07. Zlecenie Artura: „zaproponuj nowe mockupy zakładki insights…
powinny być 3 zakładki: Rekrutacja, Delivery Lead i Rada Nadzorcza — tak jak
jest w DynaReporterze", a następnie „okay, implementuj to".

Makiety (canvas, trzy pełne artboardy 1440 px + notatki):
<https://claude.ai/code/artifact/fda9a364-4b03-466c-b395-69881c3b8905>

## Co się zmieniło

| Było | Jest |
|---|---|
| `?tab=rekrutacja` · `?tab=klienci` · `?tab=zarzad` | `?tab=rekrutacja` · `?tab=delivery-lead` · `?tab=rada` |
| „Klienci & Delivery" | **Delivery Lead** — ranking DL, placementy wg klientów, hit ratio per klient, hiring managerowie |
| „Zarząd" | **Rada Nadzorcza** — KPI i finanse firmy + **ranking klientów z MRR** |
| Liga Mistrzów w Zarządzie | **Liga Mistrzów w Rekrutacji**, razem z wyścigami i Hall of Fame |
| Linki aplikacyjne w Zarządzie | **Linki aplikacyjne w Rekrutacji**, w sekcji „Źródła" |
| brak spisu sekcji | **pasek sekcji** z kotwicami w każdej z trzech zakładek |

Podział jest treściowy, nie kosmetyczny: ranking klientów i MRR odpowiadają na
pytanie o pieniądze firmy (Rada), a nie o obsadę (Delivery Lead); gamifikacja
i źródła kandydatów to rozmowa o zespole (Rekrutacja).

## Decyzje, które łatwo cofnąć nieświadomie

- **Stare identyfikatory zakładek ŻYJĄ jako aliasy** (`LEGACY_TAB_ALIASES`):
  `klienci` → `delivery-lead`, `zarzad` → `rada`. Bez nich stary link wpadał
  w gałąź „nieznany tab" i po cichu lądował na Rekrutacji — czyli link do
  kokpitu Rady otwierał co innego bez słowa wyjaśnienia. Takie linki są
  w zakładkach przeglądarki i na stronie `/dynareporter` (ta ostatnia
  zaktualizowana; `clients-mrr` prowadzi teraz do Rady, bo tam mieszka MRR).
- **Rozstrzyganie zakładki to CZYSTA funkcja** `resolveInsightsTab`, nie
  warunek w efekcie. Powód jest wprost z PR #1316: test kończący się na
  argumencie callbacka nie dowodzi, że nawigacja działa — dowodem jest
  round-trip przez warstwę, która naprawdę przenosi stan.
- **Domyślne okno Delivery Leada to ROK**, nie miesiąc. Ranking stoi na
  rekrutacjach ZAMKNIĘTYCH w oknie, a tych w miesiącu jest kilkanaście na cały
  zespół — hit ratio z takiej próbki skacze o dziesiątki punktów i czyta się
  jak awaria. DynaReporter pokazywał tu domyślnie wszystkie dane.
- **Trzy zakładki mają trzy różne domyślne okna** (Rekrutacja: poprzedni
  zamknięty miesiąc, Delivery Lead: rok, Rada: kwartał) i to nie jest dług.
- **Eksport CSV Rady to JEDEN arkusz z dwoma blokami** (`buildRadaCsvExport`),
  bo `PeriodPicker` przyjmuje jeden eksport, a zakładka pokazuje dwie tabele.
  Osobny builder na ranking klientów, którego nikt by nie podał, byłby martwym
  kodem ze 100% pokryciem — dawny `buildClientsCsvExport` osierocony
  przeniesieniem rankingu został scalony, a nie zostawiony „na potem".

## Świadomie POZA zakresem tej zmiany

- **Tabele rok-do-roku 2024/2025/2026** z kolumnami Δ i „Ocena" — sedno układu
  DR w zakładce Rady. `GET /api/insights/board` zwraca KPI okna plus trend
  miesięczny, więc trzyletnia siatka miesiąc × rok wymaga pracy po stronie
  backendu (osobne okna dla trzech lat, YTD w wierszu podsumowania,
  porównanie „te same miesiące", nie „cały rok"). Makieta pokazuje docelowy
  kształt; kod go dziś nie ma i zakładka renderuje KPI + trend + ranking.
- **„Zysk" (marża − pozostałe koszty)** — NEXUS nie zna „pozostałych kosztów";
  wymaga źródła spoza systemu. W DR ta tabela była pusta we wszystkich
  36 miesiącach.
- **Priorytety zespołu wg kategorii kompetencji** (1st/2nd priority) — dane
  istnieją wyłącznie w zamrożonych tabelach `dr_*`, nie w modelu operacyjnym.

## Weryfikacja

- `npm run type-check`, `npm run lint`, `npx vitest run` na testach Insights.
- Test kontraktowy `InsightsAccess.test.ts`: identyfikatory trzech zakładek,
  aliasy starych linków, filtr listy dozwolonych zakładek (D7 zostaje).
- Przegląd wizualny zakładek przez przeglądarkę po deployu.

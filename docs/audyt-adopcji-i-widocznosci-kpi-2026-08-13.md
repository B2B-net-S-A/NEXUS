# Audyt adopcji procesu i widoczności KPI — 2026-08-13

Pomiar na produkcji (`bd913673` → `20f7bd69`), narzędzie: `GET /api/admin/process-adoption`
(PR #1152). Naprawy: PR #1153. Wszystkie liczby poniżej pochodzą z żywej bazy, nie z estymat.

## Pytanie, na które audyt odpowiadał

Kafle „Statystyki rekrutacji" na `/dashboard` i `/api/reports/recruitment` liczyły **ten sam
lejek** i różniły się 5–15× po znormalizowaniu długości okna. Do tego sierpień 2026 wyglądał
na urwisko: 15 weryfikacji i **zero** rekomendacji, przy 500–900 i 125–272 miesięcznie.

Nie dało się z zewnątrz rozstrzygnąć, czy zespół przestał pracować, czy system przestał widzieć.
Stąd dwa pomiary w jednym: **adopcja** (czy praca dzieje się w NEXUSIE) i **widoczność**
(jeśli tak, dlaczego KPI jej nie widzi).

## Ustalenie 1 — zespół nie pracuje w NEXUSIE: 0,5%

W ostatnich 90 dniach **144 ruchy pipeline'u z 31 572** powstały w NEXUSIE. Reszta to import.

| etap | w NEXUSIE | z Traffita |
|---|---|---|
| new | 39 | 11 744 |
| screening | 25 | 7 951 |
| rejected | 1 | 5 292 |
| verified | 17 | 2 700 |
| cv_sent | 21 | 2 007 |
| interview | 2 | 1 637 |
| hired | 22 | 72 |
| client_interview | 2 | 0 |

Miesięcznie praca własna: maj 8 · czerwiec 99 · lipiec 28 · sierpień 9. To nie jest spadek —
zawsze było tyle.

Obala to hipotezę, że weryfikacja jest jedyną rzeczą klikaną w NEXUSIE: Traffit ma odpowiednik
tego etapu i importuje go (2700 wobec 17 własnych).

Powierzchnie puste, bo obsługuje je Traffit albo nikt: `interview_feedback` **0 wierszy w 90 dni**
(model wymaga `calendar_event_id NOT NULL`, więc decyzja przekazana telefonicznie nie ma gdzie
wylądować), `client_interview` **2 ruchy**, oferty zamknięte 315 — z tego **315 bez
`close_reason`**, tabela `scheduled_rejection_emails` **pusta**. Jedyna licznie używana
powierzchnia własna to kalendarz: 1676 zdarzeń.

**Dyskryminator, bez którego pomiar byłby fałszywy:** `candidate_stages.external_source = 'manual'`,
**nie `IS NULL`**. Kolumna ma ORM-owy default `"manual"`, importer stempluje `'traffit'` —
predykat `IS NULL` zwróciłby zero wszędzie, czyli prawdziwy wniosek z fałszywego powodu.
Sam `moved_by` też nie wystarcza: importer mapuje operatorów Traffita na realne `users.id`.

## Ustalenie 2 — KPI widziało 0,5% pracy, i to malejąco

Wszystkie ~53 tys. procesów w oknie 14 miesięcy mają `origin_kind='external_observed'`,
**`kpi_eligible=FALSE`**, `credit_user_id=NULL`. Obie gałęzie „classified" w
`VERIFIER_ANCHORED_CTE` wymagały `kpi_eligible IS TRUE`, więc do KPI trafiał wyłącznie kamień
milowy, który wypadł **przed** otwarciem procesu obserwacyjnego swojej pary (łapała go wtedy
gałąź `legacy_credited`). Im świeższy miesiąc, tym mniejszy udział takich milestone'ów:

| miesiąc | III | IV | V | VI | VII | VIII |
|---|---|---|---|---|---|---|
| `verified` credited/raw | 92% | 92% | 93% | 94% | **69%** | **4%** |

To nie była regresja z 1 sierpnia, tylko **postępujące wygaszanie**, które w sierpniu doszło
do końca.

Odpadanie następowało na kroku `raw → credited`. Kroki „ma credit_user" (~0%) i „credit_user
jest aktywny" (10–25%) były drugorzędne.

## Naprawy (PR #1153)

**1. Obserwacje z importu liczą się do KPI** (decyzja właściciela). Warunek nazywa
`origin_kind = 'external_observed'` zamiast zdejmować predykat — `kpi_eligible=False` bywa też
świadomym wykluczeniem z modułu priority work i te mają dalej nie liczyć się.

Efekt zmierzony po deployu, ten sam endpoint, te same okna:

| miesiąc | etap | raw | credited przed | credited po |
|---|---|---|---|---|
| 2026-08 | verified | 412 | 15 | **412** |
| 2026-08 | cv_sent | 215 | **0** | **215** |
| 2026-07 | cv_sent | 727 | 125 | 729 |
| 2026-07 | hired | 31 | 7 | 37 |
| 2026-04 | hired | 39 | 5 | 39 |

Wodospad jest teraz płaski. Placementy IV–VIII sumują się do 142, więc rocznie wychodzi rząd
300 — zgodnie z 315 z `/api/reports/recruitment`. Dwa lejki przestały się rozjeżdżać.

`credited` bywa większe od `raw` (sierpień `hired`: 20 vs 12) i to nie jest błąd: surowy widok
liczy pierwsze osiągnięcie etapu per para kandydat×oferta, CTE — per próbę procesu.

**2. Deaktywacja konta nie kasuje już wstecznie wyniku firmy.** Kafle są sumą wierszy tabeli,
a tabela pokazywała wyłącznie aktywnych — odejście rekrutera usuwało jego placementy z wyniku
całej firmy. Kwiecień jest ilustracją: 39 placementów, z czego widocznych **0**. Po naprawie 34,
a wiersze osób nieaktywnych zostają z etykietą.

**3. Kamienie milowe bez atrybucji przestały znikać.** `WHERE credit_user IS NOT NULL` wycinał
je bez śladu; teraz trafiają do `totals.unattributed` z notką pod tabelą.

**4. Talent Radar zwracał 500 na każdym realnym wyszukaniu — od wdrożenia.**
`build_ephemeral_job` nie ustawiał `hiring_manager_contact_id`, a `filter_eligible_candidates`
deleguje weto do `load_manager_rejections`, które czyta to pole **zanim** sprawdzi, czy jest
puste (`hiring_manager_verdicts.py:120`). `SimpleNamespace` nie ma domyślnych atrybutów →
`AttributeError`. Awaria omijała jedyną ścieżkę, którą ktokolwiek oglądał (pusta pula wychodzi
z `search()` wcześniej), i trafiała wyłącznie w tę, która miała działać.

Test AST, który miał tego pilnować, skanował trzy moduły i **nie** ten, w którym następuje
odczyt. Dołożony moduł zamyka dziurę, ale lista sama jest ręczna — więc obok stoi guard
puszczający pełne `search()` prawdziwym łańcuchem z podstawionym wyłącznie retrievalem.
Kontrola negatywna wykonana: bez poprawki oba testy padają produkcyjnym `AttributeError`.

## Świadomie nienaprawione

**Konwersje lejka** (`recommendation_to_interview` 291,7%, `acceptance_to_placement` 1800%).
`RecruitmentTrendChart.tsx:135` zawiera jawną wcześniejszą decyzję akceptującą >100%; sensowna
naprawa wymaga przestawienia kolejności kafli (`interview` w modelu poprzedza `cv_sent`), a po
naprawie 1 wszystkie te liczby się zmieniły. Redesign metryki przed ponownym pomiarem byłby
strojeniem na szumie. **To decyzja produktowa, nie defekt.**

## Co z tego wynika dla planów

Wszystkie programy hartujące pipeline (M4 PR-07/ledger transitions, SLA per etap, weto hiring
managera, alerty DL) dotyczą ścieżek, po których chodzi **144 ruchy na kwartał**. Nie znaczy to
„nie robić" — znaczy, że kolejność jest odwrotna niż w planach z lipca: najpierw decyzja o
przejściu zespołu, potem inwestycja w te ścieżki.

Decyzja właściciela z 2026-08-13: zespół przechodzi na NEXUS **powoli**, flow na razie zostaje
w Traffitcie, pierwszym używanym modułem ma być **Talent Radar** (stąd priorytet naprawy 4).

## Otwarte

- Weryfikacja kafli `/dashboard` i Talent Radara na żywym ruchu — wymaga zalogowanej sesji.
- Liga Mistrzów Q3: czy rozliczyć wstecznie (dziś „Brak zwycięzców" było artefaktem metryki).
- Czy Head of Recruitment ma mieć dostęp do Talent Radara — `require_candidate_write` świadomie
  go pomija.
- `SLAAlertsSection` renderuje „wszystko w normie 🎉" bez gałęzi `isError`, a `sla_max_days`
  nie jest seedowane przez żadną migrację — ekran kłamie w obie strony.
- `logger.warning` → `logger.exception` w 4 pętlach tła (poniżej progu Sentry).

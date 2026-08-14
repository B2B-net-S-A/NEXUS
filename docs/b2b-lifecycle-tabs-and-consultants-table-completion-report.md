# Cykl życia umowy B2B + tabela konsultantów w profilu klienta

> Dwie wiązki ticketów w jednym PR-ze. Część A: Generator Umów B2B (tickety 1–6).
> Część B: Klienci → Profil (tabela konsultantów + kafle KPI).

## Dlaczego

**Część A.** Kontraktor kończy projekt u klienta, ale umowa B2B **dalej
obowiązuje** — czeka na kolejne zlecenie. Rejestr nie umiał tego zapisać: `active`
twierdziłby, że ktoś pracuje, `closed` — że umowy nie ma. Nie dało się więc
odpowiedzieć na pytanie „ilu mamy dziś kontraktorów bez projektu", a to pytanie
o pieniądze. Do tego katalog powodów zamknięcia (0203) opisywał **rozstanie
z Partnerem** („Wypowiedzenie", „Porozumienie"), nie **koniec projektu**.

**Część B.** Makieta z ticketu pokazuje tabelę ze stawkami w osobnych kolumnach;
kod renderował karty z kwotami zbitymi w jedną linijkę, a Archiwum używało innego
komponentu i stawek nie pokazywało wcale. Przy okazji wyszedł defekt: profil czytał
stawki z kolumn `contracts.rate_*` i **pomijał harmonogramy**, więc kontrakt ze
stawką progresywną pokazywał starą kwotę, złą marżę i zaniżone „Aktywne MRR".

## Część A — trzy zakładki

`Generator` · **`Umowy aktywne i w trakcie podpisu`** · **`Umowy bez projektu`** ·
**`Zakończone umowy`** · `Zakresy ról (admin)`.

### Migracja `0226_b2b_generated_contract_suspended`

Trzy CHECK-i przepisane w jednej transakcji, **widen-first** (wzorzec 0224):
domena statusu → domena powodu → koherencja, która odwołuje się do obu. Kolejność
nie jest kosmetyczna: gdyby koherencja poszła pierwsza, istniałaby chwila,
w której constraint dopuszcza wartość odrzucaną przez drugą regułę.

- `contract_status` += `suspended`
- `closure_reason` = 7 nowych **+ 3 legacy** — produkcja ma wiersze `closed`, które
  je niosą; zawężenie domeny wywaliłoby `ADD CONSTRAINT`
- `closure_coherence`: gałąź „wymaga powodu i daty" obejmuje `closed` **ORAZ**
  `suspended` — „Zawieszona" bez odpowiedzi na „co i kiedy się skończyło" byłaby
  bezużyteczna dokładnie tak samo jak „Zakończona"

Plus tabela `b2b_generated_contract_status_events` (FK **ON DELETE CASCADE** —
`DELETE /generated/{id}` zwalnia numer umowy, RESTRICT zamieniłby dziennik
w blokadę tej operacji). Round-trip upgrade → downgrade → upgrade zweryfikowany na
żywym Postgresie z danymi: `suspended` reklasyfikuje się na `closed` (nie `active`
— tamten wymagałby wyczyszczenia pól, czyli utraty danych), a powód spoza starego
katalogu na `other` z czytelnym śladem po pierwotnej wartości.

### Reguły przejść

| Przejście | Reguła |
|---|---|
| `→ suspended` | **tylko z `active`** (422). Inaczej ślepy zaułek: powrót wymaga powiązanego kontraktu, a ten powstaje przy potwierdzeniu podpisu |
| `→ active` z `suspended` | wymaga `job_id`; `contract_id IS NULL` → **409** |
| `→ closed` | jak dotąd |

Przy powrocie: odczyt `closure_*` → wpis do dziennika → `Note` w Kontraktach →
wyczyszczenie pól → `job_id`/`client_id`/`client_name` z projektu.
**`render_payload` nietknięty** — podpisany DOCX jest zapisem tego, co strony
podpisały, i nie wolno go przepisać pod nowego klienta.

### Uprawnienia

`can_change_status` = **każdy, kto widzi wiersz** (`B2BGeneratorAccess` = admin /
head of recruitment / TAC / delivery lead z niepustym grafem klientów, plus
client-scope). Reguła „autor albo admin" była za wąska: kontraktora na nowy projekt
kieruje delivery, nie osoba, która kiedyś kliknęła „generuj" — przycisk byłby
niewidoczny dla większości zespołu, a cała zakładka „Umowy bez projektu" martwa.
`client_name` (korekta treści dokumentu) zostaje przy wąskiej bramce.

## Część B — tabela konsultantów

Kolumny: `Konsultant` (nazwisko / tag CC / **rekrutacja**) · `Start date` ·
`Stawka kosztowa` · `Stawka przychodowa` · `Marża`; Archiwum dokłada `End date`.
Akcje zachowane w obu (`Extend` / `ReEngage`) — ReEngage tworzy NOWY kontrakt, nie
edytuje wiersza archiwalnego.

**Naprawa stawek.** `clients.py` reużywa `app.api.contracts._effective_rate_fields`
zamiast czytać kolumny legacy. Oba zapytania dostały `selectinload` trzech
harmonogramów — bez nich helper robi lazy-load w async i leci `MissingGreenlet`
500 bez CORS. Aktywni liczą się na dziś, archiwum **na dzień zakończenia**
(`end_date` → `terminated_at` → dziś): krok harmonogramu zaplanowany po zakończeniu
projektu nigdy w jego trakcie nie obowiązywał. `active_mrr`, `total_revenue` i LTV
korzystają z tego samego źródła — kafel będący sumą innych liczb niż widoczne pod
nim nie daje się zweryfikować wzrokiem.

**Skutek uboczny do zakomunikowania zespołowi:** u klientów z harmonogramem stawek
kwoty na profilu **się zmienią** — bez żadnej zmiany danych. To intencja, nie
regresja.

`HistoricalPlacementItem` += `job_id`, `monthly_rate_candidate`,
`monthly_rate_client`, `monthly_margin` — objęte tą samą redakcją `VIEW_FINANCE`.

Kafle KPI: układ jednoliniowy (~44 px zamiast ~88), `subtitle` → tooltip.
`components/StatsCard.tsx` ma dokładnie jednego konsumenta, więc zero blast radius
(nie mylić z `components/ds/StatCard`, który ma sześć).

## Weryfikacja

| Warstwa | Wynik |
|---|---|
| BE ruff (check + format) | ✓ na 13 zmienionych plikach |
| BE pytest | `test_b2b_generated_contract_status` 42/42 · `test_b2b_status_events_migration` 12/12 · `test_b2b_generated_contract_snapshot_migration` 11/11 · `test_client_profile` 9/9 · regresje: `test_b2b_contract_generator`, `test_b2b_signature_automation`, `test_b2b_partner_entity_type`, `test_health_v2`, `test_schema_inventory`, `test_whole_pln_money_fields`, `test_ezdrowie_project_part`, `test_contract_finance_redaction`, `test_client_access_matrix` — wszystkie zielone |
| Migracja na żywym PG | `upgrade heads` ✓ · `downgrade -1` z danymi ✓ · ponowny `upgrade` ✓ · CASCADE zweryfikowany |
| FE tsc / lint / build | ✓ / ✓ / ✓ (81/81 stron) |
| FE vitest | 1166 testów; 3 flaki niezależne od zmiany (timeout 5 s pod równoległym obciążeniem, solo przechodzą 14/14) |

Nowe testy: 8 integracyjnych ścieżek cyklu życia (zawieszenie tylko z aktywnej,
409 bez kontraktu, notatka, dziennik, filtry) · 12 kontraktowych na migrację
i lustro entrypointu · 3 na stawki z harmonogramu · 11 na nowe zakładki FE ·
6 na tabelę konsultantów.

## Smoke na produkcji (2026-08-14, `e0cbda9`)

Wyłącznie ODCZYT — żadna prodowa umowa ani kontrakt nie zostały zmienione.
Pełnej ścieżki `Aktywna → Zawieszona → Aktywna → Zakończona` celowo NIE odpalono
na żywych danych (ten sam wybór co przy tickecie #5 w Fazie C); mechanika jest
pokryta 8 testami integracyjnymi.

**Wdrożenie schematu — jedyny realny dowód.** `/api/health/deep` = `healthy`,
w tym `b2b_generated_contracts` **i `b2b_generated_contract_status_events`**.
Prod ma osierocony alembic, więc zielona sonda głęboka jest jedynym potwierdzeniem,
że lustro DDL w `entrypoint.sh` faktycznie się wykonało — `/api/health` byłby
zielony także wtedy, gdyby tabela nie powstała.

**Generator.** Pięć zakładek z nowymi nazwami. „Umowy bez projektu" pusta
z komunikatem „Brak umów bez przypisanego projektu." (prawdziwe zero — awaria
renderuje alert z „Ponów"). „Zakończone umowy" pokazuje 3 realne wiersze,
read-only, bez kolumny Akcje. **Wiersz 1457/2026 niesie powód „Wypowiedzenie"** —
czyli wartość sprzed 0226 wyrenderowaną z etykietą, nie surowym kluczem. To
potwierdza decyzję o zostawieniu legacy w katalogu: zawężenie domeny zgodnie
z literalnym brzmieniem Ticketu 4 pokazałoby tu puste miejsce. Dwa pozostałe
wiersze mają powód „Inny" z własnym tekstem.

**Profil klienta (Alior, 39).** Kafle jednoliniowe. Kolumny zgodne z makietą;
marże się zgadzają (22 589 − 16 000 = 6 589). Wartość 22 589 to kontrakt godzinowy
141,18 × 160 = 22 588,80 → koercja `WholePLN` działa i wiersz się nie wywraca.
**Archiwum konsultantów** ma komplet nowych pól: koszt 19 200 · przychód 22 200 ·
marża 3 000 · **End date 30.06.2026** — przed tym PR-em API nie zwracało tam
żadnej stawki.

**Naprawa stawek — zmierzony skutek.** U PFRON (klient 122) trzy kontrakty mają
w harmonogramie obniżkę od 2026-07-01, której profil dotąd nie pokazywał:

| kontrakt | harmonogram klienta | profil po zmianie |
|---|---|---|
| 401 | 130 → **120 od 2026-07-01** | 19 200 = 120 × 160 |
| 389 | 190 → **170 od 2026-07-01** | 27 200 = 170 × 160 |
| 393 | 90 → **80 od 2026-07-01** | 12 800 = 80 × 160 |

Wszystkie zgodne z modułem Kontrakty (który zawsze liczył z harmonogramu). Przed
zmianą profil czytał kolumnę legacy — na kontrakcie 401 pokazywałby 20 800.

**Zakres zmiany jest wąski.** U Centrum e-Zdrowia harmonogramy są PUSTE
(`_effective_rate_fields` spada na kolumnę legacy), więc tam kwoty się nie
zmieniły. Nie każdy klient zobaczy różnicę — tylko ci z realnym harmonogramem.

## Dwie rzeczy zmierzone przy smoke'u, warte osobnej decyzji

**1. `Contract.job_id` jest pusty w całej bazie produkcyjnej.** Przeskanowano
10 klientów (Alior, Bank Pocztowy, BNP, e-Zdrowie, Nordea, Ergo Hestia, m-Leasing,
Nationale Nederlanden, KIR, PFRON) — **zero** aktywnych konsultantów z
`job_title`. Wiersz „rekrutacja" pod nazwiskiem jest zaimplementowany i renderuje
się poprawnie jako PUSTY (wymóg ticketu), ale dopóki kontrakty nie dostaną
powiązania z ofertą, nie pokaże niczego u nikogo. To brak DANYCH, nie kodu —
`ClientOrder.job_id` bywa wypełniony i mógłby posłużyć jako fallback, ale to
osobna decyzja produktowa.

**2. Kafel „Aktywne MRR" różni się o 1 zł od sumy kolumny „Marża"** (Alior:
59 211 vs 59 212). Każdy wiersz jest zaokrąglany osobno przez `WholePLN`
(half-up), a MRR sumuje `Decimal`-e i zaokrągla raz — suma zaokrągleń ≠
zaokrąglenie sumy. Rozbieżność jest wcześniejsza niż ten PR, ale kolumnowy układ
stawia obie liczby obok siebie, więc stała się widoczna. Naprawa to jedna linijka
(sumować wartości już zaokrąglone); świadomie NIE robiona tutaj, bo wykracza poza
zakres ticketów.

## Znane ograniczenia

- Zakładka „Umowy bez projektu" jest pusta do pierwszego zawieszenia; historia
  sprzed wdrożenia siedzi w `activities` i nie pojawi się w dialogu historii.
- Limit 100 wierszy archiwum konsultantów zostaje (bez zmian).
- Rozjazd definicji „aktywny konsultant" między profilem
  (`Contract.status IN (active, ending)`) a katalogiem klientów
  (`client_directory.py` — dodatkowo data-efektywny i dedup po osobie) **nietknięty**;
  liczniki na dwóch ekranach mogą się różnić. Warte osobnego ticketu.
- Pełna ścieżka zmiany statusu nie została odpalona na żywych danych (mutacja
  prodowych umów) — pokrycie przez testy integracyjne.

## Zauważone przy okazji, POZA zakresem

`backend/app/api/proposals_bulk.py:420` używa `NoteType.private`, a enum ma tylko
`call|meeting|email|general|interview` → `AttributeError` przy każdym niepustym
`body.note` w masowym dodawaniu kandydatów. Nietknięte w tym PR-ze.

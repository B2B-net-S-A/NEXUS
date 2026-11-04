# Konflikty z klientem (blacklist / NDA / konkurent) są OSTRZEŻENIEM, nie blokadą (decyzja Artura, 17.09.2026)

Rejestr `candidate_conflicts` (widżet „Konflikty" na profilu kandydata) do
17.09 ukrywał kandydata w wyszukiwaniu AI pod rekrutację u danego klienta
i odmawiał 409 przy dodaniu do pipeline'u. Od 17.09 aktywny, niewygasły
konflikt typu `blacklist` / `nda` / `competitor` **ostrzega**: kandydat jest
widoczny (Talent Radar, `/ai-matches`, rekomendacje, „podobne rekrutacje",
digest, ręczna wyszukiwarka), przypisywalny, z bursztynową plakietką
i polskim powodem.

| Sygnał | Widoczność | Przypisanie |
|---|---|---|
| globalna `blacklisted` (status kandydata) | ukryty | blokada |
| już w tej rekrutacji | ukryty | blokada (dedup) |
| weto hiring managera | widoczny, `severity=hard` | blokada |
| konflikt klienta, obecne zatrudnienie, wykluczenie przez kandydata | widoczny, `severity=warning` | dozwolone |

- **Jedno źródło prawdy:** `services/candidate_job_eligibility.py`. Kolejność
  bramek: globalna blacklista → duplikat → weto HM → dominujący sygnał miękki
  (`blacklist > nda > competitor > current_employment > excluded`, reszta
  w `secondary_reasons`). `override_allowed` jest ZAWSZE `False` — pole zostaje
  dla kształtu API, endpointu nadpisania nie ma i nie ma już czego nadpisywać.
- **Plakietka: `services/eligibility_annotation.py`**, dla KAŻDEGO
  `reason_code != eligible`. Do 17.09 helper zwracał `None` dla decyzji
  `eligible=True` bez sygnałów pobocznych, więc czyste „obecne zatrudnienie"
  nie miało plakietki — a po zmianie zniknęłaby też plakietka NDA.
- **Zwolnione z dealbreakerów w `/ai-matches` jest tylko weto HM**
  (`severity=hard ∧ visibility=warn`). Kandydat z NDA ponad budżet chowa się
  do `over_budget` jak każdy inny — świadomie (od 30.09.2026 budżet nie ukrywa
  nikogo poza trybem `MUST_GATE_MODE=all`). Testy, które potrzebują „widoczny,
  ale zablokowany", seedują weto HM (`tests.test_manager_rejection_gate`), nie NDA.
- **Scoring nie zeruje za konflikt ani `client_excluded`** — trafiają do
  `breakdown.warnings`; zeruje wyłącznie globalna `blacklist`. Zero trzymałoby
  kandydata pod `RECOMMENDATION_MIN_SCORE` i decyzja byłaby niewidoczna.
  Stare wiersze cache z tymi kodami w `penalties` unieważnia instrukcja
  w `_DATA_STATEMENTS` entrypointu (samoograniczająca: `stale = false`),
  a dodanie i dezaktywacja konfliktu wołają `mark_stale_for_candidate`.
- **`/seeking-contractors`:** ostrzeżenie o konflikcie klienta NIE jest
  wyłączalne checkboxem `industry_blocklist` (on steruje tylko obecnym
  zatrudnieniem — M2-SEC-03). `FilterStats.dropped_blocklist` jest zawsze 0
  i zostaje dla kształtu odpowiedzi.
- **Bulk-add:** `client_blacklist`/`client_nda`/`client_competitor` są
  w `warnings[]`, nie `skipped[]` — lustro w `candidate-search-api.ts`
  i `bulk-result-summary.ts`.
- **Obecne zatrudnienie wynika też z umów** (`services/current_employment.py`):
  `status ∈ {active, ending}` ∧ (`start_date` puste albo ≤ dziś); koniec
  rozstrzyga status, nie `end_date` (umowa B2B bezterminowa). Ręczne wiersze
  `current_employment` zostają dla pracodawców spoza naszych umów.
  `_derive_employment` w `candidates.py` celowo nietknięte.
- **Ręczna wyszukiwarka** (`POST /api/search/candidates`) niesie `eligibility`
  wyłącznie przy `exclude_in_job_id` i wyłącznie dla osoby z dostępem do tej
  rekrutacji (`ensure_job_read_access`) — plakietka ujawnia weto hiring
  managera. Bez dostępu wyniki przychodzą normalnie, bez plakietek.
- **`pipeline_eligibility` czyta konflikty KOLUMNAMI, nie encją** — gorąca
  ścieżka każdego ruchu nie może zależeć od kolumn audytu z 0321 (na prodzie
  wprowadza je safety-net z `lock_timeout`; pominięty ALTER = 500 na ruchu).
- **Rejestr (`api/candidate_conflicts.py`, migracje 0321–0322):** jeden
  AKTYWNY wpis na (kandydat, klient, **typ**); precedencja typów
  w `models/candidate_conflict.py` (`CONFLICT_TYPE_PRECEDENCE`,
  `dominant_conflict_type`, `active_unexpired_clause`). NDA wymaga daty
  wygaśnięcia. Wygaśnięcie NIE przełącza `active=false` — stan `expired`
  liczony przy odczycie, a skaner DL wystawia jednorazową kartę
  „Konflikt z kandydatem wygasł". Wygasły wpis nadal zajmuje indeks
  unikalności, więc nowy wpis tego samego typu ZAMYKA go („Zastąpiony nowym
  wpisem po wygaśnięciu") zamiast odmawiać 409. Dezaktywacja wymaga powodu
  i zostawia `Activity` (`conflict_added` / `conflict_deactivated`, same ID —
  wolny tekst powodu zostaje na wierszu konfliktu). Formularz w widżecie
  widzą tylko role z prawem zapisu (admin, Delivery Lead z zapisem Sourcing
  lub Pipeline); pozostałe widzą listę.
  Odczyt: `CandidateSearchAccess` — do 17.09 lista stała za bramką Finance
  i Delivery Lead, który mógł konflikt dodać, dostawał 403 przy jej odczycie.
  `GET /api/conflicts` zasila sekcję „Konflikty z kandydatami" na profilu
  klienta i zakładkę Ustawienia → Konflikty. Tabela nie miała wcześniej
  żadnego lustra w `entrypoint.sh` — teraz ma (kolumny, indeksy, CHECK alertu).

## Czarna lista — jedno okno „Czarna lista…” (17.10.2026)

Pytanie rekrutera, jak oznaczyć czarną listę. Pomiar produkcji 17.10: 37 osób
„Zablokowany” (wszystkie z dopisków Traffita w imieniu, ręcznie w NEXUSIE —
raz), 2 wpisy w rejestrze konfliktów w całej historii, a 74 osoby miały
notatkę „czarna lista / nie współpracujemy / nie proponować” (55 bez
statusu). Decyzja Artura („możemy zrobić, jakie proponujesz”), makiety:
https://claude.ai/artifact/UGYuAg37XJYhkAipLQyPeW.

- **Jedno wejście** w menu profilu („Status osoby” → „Czarna lista…”) i w menu
  panelu osoby na Tablicy: „U nas — nie współpracujemy” albo „U klienta — nie
  proponować do: [klient]”, powód obowiązkowy (5–2000 znaków).
  Front: `components/v2/candidate-profile/BlacklistDialogs.tsx` (okno, ramka
  `BlacklistNotice`, pigułki listy i panelu).
- **„U nas”** = status `blacklisted` jak dotąd (ukryty w wyszukiwaniu pod
  rekrutację, blokada dodania), plus kolumny `blacklisted_at`,
  `blacklisted_by_user_id`, `blacklist_reason` (0452, lustro w
  `entrypoint.sh`) — `POST /api/candidates/{id}/blacklist` `{scope: "global"}`
  (`api/candidate_blacklist.py`, `services/candidate_blacklist.py`).
  `GET /api/candidates/{id}` i szybki podgląd niosą `blacklist` {since,
  by_user_id, by_name, reason}; wpisy sprzed 17.10 mają same `null`.
- **„U klienta”** = wpis `blacklist` w tym rejestrze (ostrzeżenie, jak
  wyżej) przez `scope: "client"` — wspólne `candidate_conflicts.add_conflict`.
- **Kto:** dodaje każdy z zapisem kandydata, także rekruter (globalną listę
  mógł ustawić i wcześniej polem „Status”; wpis u klienta nic nie blokuje).
  Zdejmuje „u nas” tylko admin, Delivery Lead i Head of Recruitment
  (`POST …/blacklist/remove` z powodem; `REMOVER_ROLES`). Wpis u klienta
  zdejmuje się jak każdy konflikt. Formularz „Dodaj konflikt” (NDA,
  konkurent) dalej tylko admin i Delivery Lead.
- **Pole „Status” zniknęło z „Edytuj dane”**, a `PATCH /api/candidates/{id}`
  ze zmianą statusu na albo z `blacklisted` → 422
  `candidate_blacklist_dedicated_endpoint` — inaczej powód i autor dałyby
  się ominąć. Importy (CSV, `/bulk-import`, mapper Traffita) dalej ustawiają
  status z dopisku w imieniu, bez powodu.
- **Ślad:** aktywności `candidate_blacklisted` / `candidate_blacklist_removed`
  (szczegóły: zakres, powód, przy zdjęciu też powód dodania — kolumny są
  wtedy czyszczone). Lista kandydatów pokazuje pigułkę „Czarna lista”.
- Typ `current_employment` nie da się już dodać (422) — „Pracuje u nas”
  liczy się wyłącznie z umowy (`kandydaci-wyszukiwanie/znacznik-pracuje-u-nas.md`).

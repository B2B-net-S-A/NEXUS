# Karta klienta (`client_playbooks`) — wiedza o kliencie poza profilem Championa (wariant B)

Data: 2026-09-03

Plan: `~/.claude/plans/zaplanuj-wariant-b-od-modular-origami.md` (zatwierdzony 03.09.2026, jeden PR).

## Problem

Profil Championa (`jobs.champion_profile`, JSONB) niósł w sekcji 6 „O kliencie" i 7
„Dokumenty" fakty **per klient**, kopiowane **per rekrutacja**: opis klienta, reguły
priorytetu, off-limit, typ umowy, język CV, lista dokumentów. Do tego 14 wzorów Word
per klient wstrzykiwało pod tytułem ramkę „Standardy tego klienta" (SLA, limit CV,
blokada 24 h, onboarding, adresy biur, rozliczenia), której źródłem był plik w repo
edytowany wyłącznie przez programistę.

Zmierzone przed zmianą: pola `client.about/priority_rules/offlimit/contract_type/
cv_language` i `documents[]` nie miały ŻADNEGO konsumenta w backendzie poza edytorem;
KPI czasu na kandydata nie miało pola w bazie; `client_cv_rules` było jedyną
DL-owned tabelą per klient, ale zakresem ograniczoną do generatora CV.

## Decyzje (Artur, 03.09.2026)

- Jedno miejsce prawdy per klient: `client_playbooks` (1:1, DL-owned, wersja +
  historia, bez bramki zatwierdzenia). Tabela-siostra reguł CV, nie kolumny w nich
  (edycja obowiązującej reguły CV zdejmuje zatwierdzenie).
- Edycja w dwóch miejscach jednym formularzem (`ClientPlaybookForm`): zakładka
  „Karta klienta" w `/settings/cv-rules?client=<id>&tab=playbook` oraz w miejscu
  w profilu klienta (zakładka „Zasady współpracy").
- Pomoc → Klienci = procedura per klient generowana z karty; seed KOMPLETNY
  (każda linia 14 wzorów trafia do karty, w tym linie o pochodzeniu kandydata
  i o nazwie pliku/języku CV).
- 14 wzorów Word per klient wycofane z Pomocy (`is_published=false`; wiersze i pliki
  zostają); jeden generyczny wzór.
- Odczyt karty org-wide dla ról operacyjnych (karta zastępuje wzory czytane przez
  każdego zalogowanego); zapis i historia jak reguły CV po #1351 (sekcja Delivery +
  portfel DL przez `resolve_client_access`); `off_limits` tylko dla ról z odczytem
  sekcji Delivery.
- `selling_points`/`consultant_insight`/`historical_questions` zostają per
  rekrutacja (zasilają wektor oferty i prompt CV; przeniesienie wymaga A/B).

## Co zostało zmienione

Backend:
- `app/models/client_playbook.py`, `app/models/client_playbook_event.py` + rejestracja
  w `app/models/__init__.py` i sondzie startowej `app/main.py`.
- `app/api/client_playbooks.py`: `GET /api/clients/{id}/playbook` (`OperationalUser`),
  `PUT` (`DeliverySectionUser` + `can_edit_knowledge`), `GET …/history`
  (`DeliverySectionUser` + `can_view_knowledge`), `GET /api/settings/client-playbooks`
  (`OperationalUser`, bez zawężania do portfela).
- Migracja `0272_client_playbooks` (← `0271_default_template_interview`, po `0270_jobs_open_state_dates`): dwie tabele,
  seed 14 kart z `app/data/client_playbooks/seed.json` (dokładnie jeden żywy klient
  po wzorcu nazwy z 0255, `ON CONFLICT (client_id) DO NOTHING`), odpublikowanie
  14 wzorów w `help_materials`.
- `entrypoint.sh`: lustro DDL w `_COLUMN_STATEMENTS`, `_seed_client_playbooks(conn)`
  po `_seed_repo_procedures`, odpublikowanie w `_DATA_STATEMENTS` z markerem
  `0272_champion_client_templates_unpublished` w `app_settings`.
- Parser Championa v6 (`champion_parse:v6:haiku-4.5`): trzy układy dokumentu, blok
  `client` bez pól karty klienta, bez `documents`; `build_champion_dict` emituje puste
  wartości (kształt siedmiu kluczy zostaje).
- `scripts/generate_champion_template.py`: jeden generyczny wzór, 6 sekcji, bez ramki
  standardów i sekcji „Dokumenty", odsyłacz do karty klienta pod sekcją 6;
  `scripts/champion_template_clients.json` usunięty (konwersja:
  `scripts/build_client_playbook_seed.py` z kontrolą kompletności).

Frontend:
- `lib/client-playbooks.ts` (typy, API, hooki, mapowanie formularza), capability
  `client_playbook.manage` (rola + sekcja Delivery/write + `MUTATING_CAPABILITIES`).
- `components/client-playbook/ClientPlaybookCard.tsx` (full/compact, cztery stany),
  `ClientPlaybookForm.tsx` (jeden formularz: load/save/historia), `ClientPlaybookTab.tsx`
  (profil klienta: karta ↔ formularz), `cv-rules/CvRulePlaybookTab.tsx` (zakładka
  edytora reguł CV, montowana leniwie, `initialTab` + `?tab=` na stronie ustawień).
- Profil klienta: zakładka „Zasady współpracy" (`client-tab.ts` → `zasady`).
- `ChampionProfileEditor.tsx`: sekcja 6 z kartą compact, bez pól `about`,
  `priority_rules`, `contract_type`, `offlimit`; sekcja 7 usunięta (typy i payload
  bez zmian — dane legacy w JSONB zostają).
- Pomoc: zakładka „Klienci" (`HelpClientPlaybooksSection.tsx`, `?tab=clients&client=<id>`).
- Harness `/preview/client-playbook` (zero wywołań API) + `PUBLIC_PATHS`.

Docs: sekcja „Profil Championa — sześć sekcji + karta klienta" i nowa „Karta klienta
(`client_playbooks`)" w `CLAUDE.md`.

## Seed i wycofanie wzorów

`seed.json` = 14 kart. Liczby zasiane tylko tam, gdzie wzór podawał je wprost:

| Klient | SLA dni | min. kand. | limit CV | blokada h | karencja dni |
|---|---|---|---|---|---|
| BNP Paribas | 10 | 2 | 6 | — | 14 |
| Nordea | 5 | 1 | — | 24 | — |
| Tauron | 5 | 1 | — | 24 | — |
| PFRON | 10 | 1 | — | 24 | — |
| PANSA | 5 | — | 3 | 24 | — |
| Bank Pocztowy | — | — | 2 | 24 | — |
| PKO BP | — | — | — | 24 | — |
| ENERGA, ORLEN | — | — | 5 | — | — |
| ALIOR | — | — | 2 | — | — |
| BIK, Santander, KIR, Credit Agricole | — | — | — | — | — |

Wzorce dopasowania klienta (z 0255) wieloznaczne przy kilku żywych klientach (np.
`%bnp%`) NIE zasieją nic — po deployu lista kart, które powstały, jest w logach startu
(`client playbook seed ok: …`); brakujące DL zakłada z edytora, treść w `seed.json`.

Jedna korekta treści źródłowej w seedzie: wzór PFRON niósł zdanie o sprzęcie „zapewniany
przez **bank Nordea**" (kopiuj-wklej z wzoru Nordei) — na karcie PFRON zneutralizowane do
„przez klienta"; DL potwierdza przy pierwszej edycji. Pilnuje tego
`test_seed_never_names_another_client_in_card_text`. Pozostałe wady źródła (literówki
w ENERGA/ORLEN) zostają — to treść wzorów, poprawia ją DL w edytorze.

## Testy (lokalnie, 03.09.2026)

Backend (obraz `nexus-verify:img`, świeża baza `nexus_playbook`, `alembic upgrade heads`
0270_jobs_open_state_dates → 0271_default_template_interview → 0272_client_playbooks, jedna głowa):

| Zestaw | Wynik |
|---|---|
| `test_client_playbooks_api.py` (16 kontraktów: wersjonowanie, diff, walidacja, sekcje/role, portfel DL, off_limits, przegląd, trasy, seed + lustro, wyścig pierwszego zapisu → 409, seed bez cudzej nazwy klienta) | 16 passed |
| `test_champion_template_agenda.py` + `test_champion_profile_ingest.py` (wzór 6-sekcyjny, prompt v6, kształt słownika) | 49 passed |
| `test_route_authz_contract.py` + `test_section_access.py` + `test_no_new_alembic_heads` | 20 passed |
| `test_entrypoint_ddl_guards.py` + `test_ai_feature_enum_entrypoint_mirror.py` + `test_help_materials.py` | zielone solo; para `ddl_guards` → `help_materials` daje 36 błędów TAKŻE na `origin/main` (test podmienia `asyncpg` atrapą bez sprzątania — stan zastany, poza zakresem) |

Ruff 0.15.22 (`check` + `format --check`) na zmienionych plikach `app/`: czysto.

Frontend (`npm ci --legacy-peer-deps` w worktree): `type-check` czysty, `lint` bez nowych
ostrzeżeń, Vitest celowany (client-tab, capabilities, middleware, client-playbook/*,
cv-rules/*, settings/cv-rules, help-client-playbooks, help-materials): 10 plików,
481 testów zaliczonych. Pełny suite `--no-file-parallelism`: faile wyłącznie w plikach
nietkniętych tą zmianą, identyczne na commicie bazowym (stare recharts w środowisku,
timeouty jsdom przy obciążeniu) — zero regresji. Harness `/preview/client-playbook`
(pełna karta, brak karty, compact, awaria) obejrzany w przeglądarce.

## Po deployu (ręcznie)

- Logi startu: `client playbook seed ok: …` — policzyć, ile z 14.
- SharePoint: podmiana ogólnego wzoru Word plikiem z
  `python scripts/generate_champion_template.py --out-dir …`.
- Chrome: DL — `/settings/cv-rules?client=<id>&tab=playbook`, `/clients/<id>?tab=zasady`
  (edycja w miejscu), rekrutacja → Champion → sekcja 6; recruiter — karta compact na
  rekrutacji, „Pełna karta klienta →" do Pomocy; Pomoc → Materiały bez 14 wzorów.

## Poza zakresem (świadomie)

- `DELETE` i `copy-from` karty (wzorzec z reguł CV).
- Przeniesienie atutów/insightu/historycznych pytań na poziom klienta (A/B na wektorach).
- Automatyzacja z pól strukturalnych: odliczanie SLA, ostrzeżenie przy wysyłce CV po
  terminie, alert `dl_alerts`.
- Generowanie kategorii „Onboarding — klient" w Pomocy z listy dokumentów karty.

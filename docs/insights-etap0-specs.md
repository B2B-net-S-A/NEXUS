# SPEC WYKONAWCZY — D5 / D6 / D7 + Etap 0

Repo: `/Users/arturtwardowski/NEXUS/.claude/worktrees/insights-rekrutacja-nexus-data-dc14e9`
Plan bazowy: `docs/insights-dynareporter-migration-plan.md` (§0 = D1-D7, §5 = etapy)

---

## A. D5 — dni robocze z COMPASS

### A.0 Werdykt: **NIE BUDUJEMY INTEGRACJI TERAZ.** Warunek wstępny jest obalony, nie „niezmierzony".

Plan sam warunkuje D5 na pomiarze (`docs/insights-dynareporter-migration-plan.md:20`: „Warunek: pokrycie zespołu rekrutacyjnego w COMPASSIE — do zmierzenia przed budową"). Pomiar nie przeszedł, a przy okazji wyszło, że teza „strefa HR COMPASSA obejmuje wszystkich poza konsultantami IT, więc rekruterzy są w środku" jest **fałszywa**. Siedem twardych faktów, każdy z pliku:

1. **`is_internal_or_admin()` to DWIE role, nie pięć.** `supabase/migrations/20260507120001_phase11b_hr_internal_schema.sql:25-31` — `role IN ('admin','internal')`. Policy INSERT na `leave_requests` jej wymaga (`:246-252`, po Phase 25b `20260518000002_phase25b_leave_on_behalf.sql:48-54`), a `createLeaveRequest` idzie klientem związanym RLS (`lib/actions/internal-leave.ts:452,466,552-570`). **`manager`, `finanse`, `talent_community` nie złożą wniosku urlopowego same** — przechodzą tylko bramkę aplikacyjną `canAccessInternalZone` (`lib/types/role.ts:71-79`) i odbijają się od RLS. Mylący jest komentarz przy `has_hr_zone_access()` (`20260516000002_phase20b_manager_id_and_helpers.sql:124-134`), który twierdzi „wszyscy poza consultant IT", podczas gdy ciało funkcji to `SELECT public.is_internal_or_admin()`.
2. **COMPASS skasował pojęcie rekrutera.** `20260504000002_phase1_role_enum.sql:6-7,22-23` przemapował `recruiter|delivery_lead|finance|centrala|administrator` → `admin` przy pivocie na platformę retencji konsultantów. Żywy enum: `lib/types/role.ts:17-24` = `consultant|admin|internal|finanse|manager|talent_community`. COMPASS **nie umie odpowiedzieć na pytanie „kto jest rekruterem"** — rosterem musi być NEXUS.
3. **Przynależność do strefy HR to ręczna flaga, nie własność bycia pracownikiem.** `profiles.role` DEFAULT = `'consultant'` (`20260504500002_phase15_role_enum_cast.sql:33`), a `sync_user_role` przy KAŻDYM logowaniu wraca do `consultant`, jeśli wiersz nie trzyma jednej z czterech zachowanych wartości (`20260516000004_phase20d_sync_user_role_v3.sql:41-56`). `internal` nadaje admin ręcznie (`lib/actions/user-admin.ts:337-375`; własny raport COMPASSA `docs/internal-role-fix-completion-report.md:36-38,60-66` wymienia jedną osobę). Pokrycie = „czy ktoś pamiętał kliknąć", a pominięcie wygląda identycznie jak „ta osoba nie brała urlopu".
4. **Rozjazd domen zabija join po e-mailu.** COMPASS twardo trzyma `@b2bnetwork.pl` w czterech miejscach: `app/auth/callback/route.ts:7` (+ wylogowanie `:38-43`), `app/login/actions.ts:82` i `:178-179`, `app/api/cron/m365-profile-resync/route.ts:36,42`. NEXUS jest w migracji na `@inframinds.eu` i ludzie mają **po dwa aktywne konta** (`backend/app/api/team_structure.py:572-575`, dedup `:611-632`, test `backend/tests/test_team_structure_dl_clients_dedup.py:67`). Ostatni commit COMPASSA jest z 2026-07-15, siedem tygodni PO tej migracji — rozjazd jest aktualny. Naiwny `lower(email)=lower(email)` przypnie urlopy do konta LEGACY, czyli martwego, a konto SSO (to, w którym powstają dzisiejsze `candidate_stages.moved_by`) zostanie bez mianownika. To nie jest „nietrafienie" — to jest trafienie w zły wiersz.
5. **Nawet przy pełnym pokryciu mianownik jest urlopowy, nie kadrowy.** `employment_type` DEFAULT = `'b2b'` z komentarzem „wszyscy pracownicy są B2B" (`20260511000002_employment_type_default_b2b.sql:2`), a trigger Phase 29 rzuca wyjątkiem na każdy `leave_type` inny niż `'vacation'` dla b2b/zlecenie (`20260530000001_phase29_b2b_zlecenie_vacation_only.sql:38-90`). **Chorobowego dla rekrutera B2B nie da się w COMPASSIE zapisać w ogóle.**
6. **Lifecycle nie żyje.** Audyt samego COMPASSA (`docs/people-ops-unify-plan.md:33`): wszystkie wiersze `employment_status='active'`, `termination_date` NULL w 100%, wniosek autora — „status NIE jest źródłem prawdy o lifecycle". Czyli przycinanie mianownika do okna zatrudnienia byłoby no-opem.
7. **Jedyna produkcyjna arytmetyka dni roboczych w COMPASSIE jest zepsuta i świadomie wyklucza B2B.** `app/api/internal/payroll-export/route.ts:66-88` filtruje `.in('role',['internal','admin'])` i potem `employment_type !== 'b2b'`; frekwencję filtruje po `status === 'present'` (`:206-211`), wartości, której nie ma w CHECK (`20260529000001_attendance_status_full_leave_types.sql:33-54`), więc jej `attendance_days` jest trwale zerowe; daty buduje przez `new Date(y,m-1,d).toISOString()` (`:149-156`) = przesunięcie o dzień w Europe/Warsaw. **Nie portować tego kodu.**

Zmierzone na żywym prodzie COMPASSA (projekt `shduiynzemftkqqefscd`): `select count(*) from public.profiles` = **46**. Pozostałe zapytania odrzucił klasyfikator uprawnień — pokrycia nie zmierzyłem i nie udaję, że zmierzyłem.

### A.1 Co robimy NATYCHMIAST, bez COMPASSA — bo defekt jest po naszej stronie

Defekt D5 to nie „brak dni roboczych". To **dzielenie przez zmyśloną liczbę i publikowanie wyniku imiennie**. Usuwamy dzielnik. To jest PR na jeden plik, bez migracji, bez zależności zewnętrznej, i po nim nikt na urlopie nie ląduje na liście „poniżej progu".

**Plik: `backend/app/api/reports.py`**

- `:1855` — **skasować** `POWER_CALLING_WORKDAYS = 5`. `POWER_CALLING_TARGET_PER_DAY = 3` (`:1854`) zostaje.
- `:1967` — `per_day = round(cnt / POWER_CALLING_WORKDAYS, 2)` → **usunąć**. Nie zastępować niczym: nie ma 21, nie ma „dni robocze z kalendarza", nie ma nic. Mianownika nie znamy.
- `:1976-1982` — wpis per osoba przestaje nieść `per_day`, `workdays` i `progress_pct`; niesie:
  ```python
  "verifications_week": cnt,
  "per_day": None,
  "workdays": None,
  "workdays_source": "unavailable",   # jedyna dziś możliwa wartość
  "meets_target": None,               # None, nie False — nikt nie minął progu, bo progu nie da się policzyć
  ```
- `:1996-2004` — koperta: `"workdays"` (stała) wypada; `requirement_text` (`:1998-2001`) przestaje mówić „na dzień roboczy" i brzmi **„Wymóg: min. 15 weryfikacji tygodniowo (3/dzień × 5 dni). Mianownik dzienny niedostępny — brak danych o nieobecnościach."**; `entries` rozbić na trzy listy: `below_target` (pusta, dopóki nie ma mianownika), `met_target` (pusta) i **`not_assessable`** (wszyscy, z `reason: "no_workday_data"`).
- **Próg tygodniowy jako tymczasowy zamiennik jest dopuszczalny** i lepszy od zera: `verifications_week >= 15` można pokazać jako liczbę bezwzględną z etykietą „15/tydz." — ale **bez nazywania kogokolwiek „poniżej progu"**, bo tydzień urlopu daje 0 i tak samo wygląda jak tydzień lenistwa. Jeśli chcesz to mieć, dodaj pole `weekly_total_only: true` i renderuj ranking bez czerwieni.

**Frontend:** `/api/reports/power-calling` **nie ma dziś ŻADNEGO konsumenta w `frontend/src`** (grep = 0 trafień). Czyli PR jest czysto backendowy i zeruje ryzyko, że ktoś ten widget podniesie razem z dzielnikiem.

**Test regresji (obowiązkowy):** `backend/tests/test_power_calling_denominator.py` — user z 0 weryfikacji w tygodniu ląduje w `not_assessable`, **nie** w `below_target`, i `meets_target is None`.

**Ta sama choroba, drugi mianownik:** kafel „CV/MD target 5" liczy dziś dzielnik jako `COUNT(DISTINCT report_date)` (`backend/app/api/linkedin_metrics.py:236,260`, `backend/app/api/dynareporter_rekrutacja.py:384`), czyli **nagradza nieuzupełnianie raportu** — kto zaraportował jeden dzień, ma 100%. Do czasu bramki: renderować liczby bezwzględne + `days_reported` obok, nigdy ilorazu jako „% targetu".

### A.2 Bramka pomiarowa — dopiero jej wynik odblokowuje integrację

Uruchom w tej kolejności. Bez tego nie zaczynamy pisać kodu integracji.

**A2.1 — COMPASS (Supabase SQL editor, projekt `shduiynzemftkqqefscd`). Kto może w ogóle złożyć wniosek:**
```sql
SELECT p.role::text AS role,
       COALESCE(p.employment_type,'(null)') AS etype,
       count(*) AS people,
       count(*) FILTER (WHERE p.is_external) AS bez_logowania,
       count(*) FILTER (WHERE lv.n > 0) AS zlozyli_12m,
       COALESCE(sum(lv.n),0) AS wnioskow_12m
FROM public.profiles p
LEFT JOIN LATERAL (
  SELECT count(*) n FROM public.leave_requests l
  WHERE l.user_id = p.id AND l.status='approved'
    AND l.end_date >= CURRENT_DATE - INTERVAL '12 months') lv ON TRUE
GROUP BY 1,2 ORDER BY 1,2;

-- ile urlopów wpisał ktoś ZA kogoś (jeśli dominuje, to §A.0 pkt 1 jest potwierdzone empirycznie)
SELECT count(*) FILTER (WHERE created_on_behalf) AS na_zlecenie,
       count(*) FILTER (WHERE NOT created_on_behalf) AS samodzielnie
FROM public.leave_requests WHERE status='approved';
```

**A2.2 — COMPASS, roster do diffu:**
```sql
SELECT lower(p.email) AS email, p.role::text AS role, p.employment_type,
       p.employment_status, p.hired_at, p.termination_date, p.is_external
FROM public.profiles p ORDER BY 1;
```

**A2.3 — NEXUS. Prod DB jest nieosiągalny (martwy SSH), więc przez API z JWT admina:**
```bash
curl -fsSL -H "Authorization: Bearer $JWT" https://api.nexus.dynaminds.pl/api/admin/users \
 | jq -r '.[] | select(.is_active)
          | select((.roles + [.role]) | any(. == "sourcer" or . == "tac" or . == "recruiter"))
          | [(.email|ascii_downcase), .role] | @tsv'
```
(`backend/app/api/admin.py:136-171`, kształt odpowiedzi `:49-62` — zwraca email/name/role/roles/is_active.)

**A2.4 — kalendarz świąt (osobny killer):**
```sql
SELECT year, count(*), min(date), max(date) FROM public.public_holidays GROUP BY 1 ORDER BY 1;
```
Oczekiwane: 2026 → 12, 2027 → 12 i **koniec** (seed `20260507120001:75-101` nie ma nic po `2027-12-26`; druga, niezależna kopia listy w kodzie `lib/utils/business-days.ts:8-35` z własnym TODO). Każdy okres od 2028-01 zawyża dni robocze po cichu.

**Kryterium GO:** niech `N` = aktywni w NEXUSIE `sourcer|tac|recruiter`, którzy ruszyli kandydata w ostatnich 90 dniach. Niech `C` = ci z nich, których e-mail (po `lower()`) trafia w wiersz A2.2 **o roli `admin` albo `internal`** (nie „którejkolwiek z pięciu"). **`C/N < 0,8` → NO-GO**, zostajemy przy A.1 na stałe i nie budujemy integracji. Dopisanie do `C` osób z rolą `manager|finanse|talent_community` jest dozwolone **tylko** jeśli A2.1 pokaże, że dla nich urlopy realnie wpadają ścieżką „na zlecenie".

### A.3 Jeśli bramka przejdzie — architektura (żeby nie budować dwa razy)

Zapisuję kontrakt, nie kod. Cztery decyzje, których nie wolno odwrócić:

**1. Kierunek: COMPASS PUSHUJE do NEXUSA. Nie pullujemy.**
Pull oznacza, że NEXUS trzyma sekret COMPASSA. `CRON_SECRET` odpada natychmiast: odblokowuje 18 tras `app/api/cron/*` **oraz** `app/api/migrate-compliance/route.ts`, którego własny komentarz (`:96-99`) mówi, że trasa uruchamia `exec_sql` kluczem service-role, czyli „any auth gap = full destructive DB access". `withCronAuth` jest dodatkowo jawnie nie-timing-safe (`lib/api/with-auth.ts:26-29`) i wciąż przyjmuje `?secret=` (`:38-40`) — dokładnie ta klasa defektu, którą NEXUS już raz usunął (CloudTalk `POST /api/calls/webhook/{token}`, CLAUDE.md §CloudTalk M6-P0.12). `COMPASS_DSN`/asyncpg odpada tym bardziej: kopiuje semantykę podziału urlopu płatnego do drugiego repo i kładzie surowe wiersze `leave_requests` (z `leave_type`, `note`, `documentation_url`) na drucie.
Push = COMPASS trzyma nasz `nxs_v2_…` — poświadczenie, które **wygasa** (`expires_at` NOT NULL), da się **odwołać bez przestoju** (dwie tabele, jedna tożsamość, N kluczy) i jest **atrybuowalne w logach**. Nowy scope w `backend/app/models/service_account.py:76-78` (`hr_workdays = "hr:workdays"`) + wpis do `SCOPE_LABELS` — **bez migracji**, kolumna trzyma stringi. Argument „COMPASS nie ma schedulera" jest fałszywy: 18 tras crona już coś odpala mimo braku `.github` i `vercel.json`. **Pierwsze zadanie: ustalić CO je odpala** — to wyznacza promień rażenia i procedurę rotacji.

**2. Payload to LISTA KOLUMN, nie filtr.** `{email, day, weight ∈ {0.5, 1.0}}` + kalendarz dni roboczych + flaga `calendar_complete`. SELECT wymienia kolumny z nazwy i **nigdy** nie zawiera `leave_type`, `note`, `decision_note`, `documentation_url`, `paid_days`, `unpaid_days`, `full_name`. Połowa z 16-elementowej domeny `leave_type` (`20260527000001_phase27k_leave_types_and_balance.sql:23-43` + `20260528000001_holiday_in_lieu_leave_type.sql:25-46`) to dane o zdrowiu i rodzinie. Test asertuje na **zserializowanym stringu** odpowiedzi, nie na kształcie — asercja kształtu przechodzi w dniu, w którym ktoś doda pole przelotowe.
**Dodatkowa pułapka, której nikt nie zauważył:** trigger `leave_requests_auto_approve_sick` (`20260507120001:207-222`) ustawia `status='approved'` dla `sick_leave` automatycznie. Czyli liczba dni **z definicji wchłania L4** — a pod D7 widzi ją każda rola. To jest do świadomej decyzji Twojej, nie do przemilczenia: albo nigdy nie renderujemy kolumny „dni nieobecności" (tylko mianownik i etykietę pokrycia), albo gasimy wskaźnik dzienny poniżej progu zmierzonych dni.

**3. Zero drabinki fallbacków.** Trzy stany i koniec: `coverage="ok"` → licz; `no_compass_profile` / `calendar_gap` / dane starsze niż jeden interwał syncu → `per_day=None`, `meets_target=None`, wiersz do `not_assessable`. **Nie ma rungu „kalendarzowe dni robocze"** — mianownik zakładający zero nieobecności JEST tym defektem, a etykieta `days_source` nie cofa czerwonego `meets_target` obok czyjegoś nazwiska.

**4. Tożsamość to TABELA FAKTÓW, nie inferencja.** `compass_person_link(nexus_user_id, compass_profile_id, compass_email, match_method, linked_at)`, `match_method ∈ {azure_oid, email, domain_alias, manual}`. **Kardynalność jeden-do-wielu** (jedna osoba = dwa konta NEXUSA po migracji domeny) — **żadnego UNIQUE na `compass_profile_id`**. Tier „ten sam localpart na dowolnej domenie, auto-akceptowany" **odpada**: `users` zawiera adresy na obcych domenach utworzone dosłownie z operatorów Traffita (`backend/app/services/traffit/importer.py:1425-1428`), więc taki tier potrafi przypiąć urlop jednej osoby do drugiej na raporcie, który wymienia nazwiska. Docelowy klucz to `azure_oid` (NEXUS ma go już: `backend/app/models/user.py:186-188`, zapis `backend/app/api/auth_microsoft.py:404,441,479`); COMPASS go nie utrwala — `lib/m365/people-sync.ts:107-110` woła Graph bez `id`. Uwaga: ta trasa Graph rozwiązuje osobę **po UPN/e-mailu**, więc przy rozjeździe domen backfill zwróci 404 połykane jako `user_not_found_in_tenant` (`:113-125`) i po cichu nie zrobi nic.

**Konwencje przy tabelach (obowiązkowe):** lustro DDL w `backend/entrypoint.sh` — do listy `_COLUMN_STATEMENTS` (start `:622`, wzorzec `CREATE TABLE IF NOT EXISTS dl_alerts` `:3405`), **nie** przez `Base.metadata.create_all`; wpis do `core_checks` w `backend/app/main.py:2028`; jedna głowa alembica (aktualna: `0249_order_rate_snapshots_offboarding` — potwierdź `alembic heads` przed pisaniem).

---

## B. D6 — seniority z placementów

### B.1 Reguła (do wpisania w CLAUDE.md razem z definicją placementu z D2)

Nazwa w UI: **„Ścieżka rozwoju"**. Poziomy jak w DR: `junior → senior → expert`.

- **Placement** = D2: pierwsze `hired` per para (kandydat, oferta), atrybuowane do `credit_user` z `VERIFIER_ANCHORED_CTE` (`backend/app/services/kpi_panel.py:123`). Data w Europe/Warsaw, kubełek = miesiąc kalendarzowy. **Dedup jest arytmetyką, nie kosmetyką** — CTE `credited` (`kpi_panel.py:278-284`) emituje więcej niż jeden wiersz `hired` na parę, gdy para ma dwa podejścia procesowe.
- **Junior → Senior:** pierwszy miesiąc `M`, w którym (placementy w 6 miesiącach kończących się `M`) ≥ 6 **albo** (w 12 miesiącach kończących się `M`) ≥ 12.
- **Senior → Expert:** ta sama mechanika, ale liczone **tylko** placementy od `senior_since` w górę i oceniane od miesiąca `senior_since`: ≥ 12 w dowolnych 6, ≥ 24 w dowolnych 12. Kotwiczenie zegara eksperta na `senior_since` to semantyka oryginału (`InfraReporter/server/src/routes/kpi.ts:4823-4832`) i to ona blokuje kupowanie dwóch awansów za te same placementy.
- **Moment awansu:** pierwszy dzień miesiąca PO miesiącu kwalifikującym (`firstOfNextMonth`, `kpi.ts:4699-4701`).
- **Okno kroczące, RESET WYRZUCAMY.** Reset 12-miesięczny w DR (`kpi.ts:4800-4808`, drugi blok `:4852-4860`) istniał tylko po to, żeby ograniczyć licznik kumulatywny liczony od stałej kotwicy. Okno kroczące ogranicza się samo. Do tego kotwica nie ma natywnego odpowiednika: `backend/app/models/user.py:76-221` nie ma żadnej daty zatrudnienia, a `created_at` (`backend/app/models/base.py:14-18`) dla kont utworzonych przez import Traffita (`backend/app/services/traffit/importer.py:1422-1441`) to data importu. Kotwica byłaby fikcją z datą. Port NEXUSA już zresztą po cichu przeszedł na okna kroczące (`backend/app/api/dynareporter_rekrutacja.py:1175-1176`).
  **Konsekwencja do pokazania przed zatwierdzeniem progów:** bez resetu „6 w dowolnych 6 miesiącach" znaczy, że jeden placement miesięcznie przez pół roku daje Seniora.
- **Degradacji NIE MA, i jest darmowa.** `senior_since` to MINIMUM miesiąca kwalifikującego po całej historii, więc funkcja jest zapadką: nowe miesiące mogą tylko przesunąć datę wcześniej albo zostawić. Rok bez placementu nie rusza poziomu; liczniki bieżącego tempa spadają do 0/0. Uzasadnienie merytoryczne: poziom to stwierdzenie o tym, co ktoś osiągnął; odbieranie go za cichy kwartał jest decyzją płacową, nie analityczną. Sygnał „przestał dowozić" żyje w osobnym, nielepkim badge'u `behind`.

### B.2 Liczone przy odczycie, NIE przechowywane — plus jeden dziennik append-only

Poziom to czysta funkcja osi czasu placementów, liczona per żądanie. Zero stanu awansu, zero joba promującego, **zero mutacji w GET**. Oryginał wystawiał w GET do sześciu rodzajów `UPDATE users SET …` (`kpi.ts:4729-4869`), a port NEXUSA „naprawił" to, usuwając silnik awansów w całości — stąd ekran, który na zawsze wyświetla „Awans od <pierwszy dzień następnego miesiąca>" (`backend/app/api/dynareporter_rekrutacja.py:1136-1144`). Przechowywanie poziomu odtworzyłoby dokładnie to, co D6 kasuje: `dr_user_seniority`, którego jedyny writer (`backend/app/api/dynareporter_admin_users.py:206-238`) jest martwy za 409 (`backend/app/main.py:418-424`, `DYNAREPORTER_MODE=read_only`), a którego czytelnik chowa każdego bez zaseedowanego wiersza (`dynareporter_rekrutacja.py:1193-1196`: `WHERE s.acceleration_start_date IS NOT NULL`).

Koszt, który mierzę i nie zamiatam: **gdy zmieni się historyczna ATRYBUCJA, poziom zmieni się po cichu, a zdegradowany wiersz wygląda identycznie jak świeżo zatrudniony** (`junior`, `first_credited_month = NULL`). Dlatego dziennik jedzie w tym samym PR:

`insights_seniority_snapshots(user_id, snapshot_date, level, senior_since, expert_since, placements_6m, placements_12m)` — jeden wiersz na (user, dzień), pisany **nocnym taskiem**, nigdy handlerem żądania, `ON CONFLICT (user_id, snapshot_date) DO NOTHING` (repo trzyma ~25 pętli w tle bez leader-election, więc duplikat workera musi być nieszkodliwy). Nigdy nie czytamy go, żeby odpowiedzieć „jaki poziom ma X" — czytamy, żeby odpowiedzieć „co mówiliśmy wczoraj". Przy odczycie: jeśli dzisiejszy poziom różni się od najnowszego snapshotu o innym poziomie, odpowiedź niesie `regression: {from, to, observed_on}`, a UI mówi wprost: **„Poziom zmienił się <data> — zmieniła się atrybucja historycznych placementów, nie wynik pracy."**

### B.3 Nieatrybuowana historia — trzy różne wiersze, nie jeden

1. **Przypisane do realnego usera** → liczy się. Uwaga: większość to ruch z Traffita przypisany temu operatorowi, którego e-mail się dopasował (`backend/app/services/traffit/importer.py:1390-1418`), często do konta `is_active=false` utworzonego przez sam import.
2. **`credit_user IS NULL`** → liczba **org-level obok sekcji**, nigdy w czyimś wierszu. Wzorzec i uzasadnienie już w repo: `backend/app/services/kpi_team.py:117` (`unattributed`) i `:196-204`. D1 wymaga tego od pierwszego dnia.
3. **Zero atrybuowanej historii** (`first_credited_month IS NULL`) → **NIE renderować „Junior · 0/6"**. Osobny badge `no_data`: „Brak przypisanych placementów w NEXUSIE — poziom nie jest liczony", plus liczba nieatrybuowanych obok jako wyjaśnienie. Każdy wiersz niesie `first_credited_month` i etykietę „dane od <miesiąc>". `users.created_at` można pokazać jako miękką podpowiedź („konto od <data>"), ale **opisaną jako data konta**, nie zatrudnienia.

**Populacja:** `u.role::text IN ('sourcer','tac','recruiter') OR u.roles ?| ARRAY['sourcer','tac','recruiter']` — dosłownie predykat z `backend/app/services/competitions.py:254-257`. Świadomie **nie** `_OPERATIONAL_ROLES` (`backend/app/services/kpi_panel.py:44-49`), bo tamten wciąga `delivery_lead`. Nieaktywnych z dorobkiem **włączamy**, oflagowanych `is_active=false` — jak `kpi_team.py:239-262`; historia firmy nie może się zmieniać od przestawienia flagi konta.

### B.4 Pliki

**Nowe:**
- `backend/app/services/insights_seniority.py` — stałe `SENIORITY_PATH_ROLES = ("sourcer","tac","recruiter")`, `DEFAULT_THRESHOLDS = {"senior_short":6,"senior_long":12,"expert_short":12,"expert_long":24}`; SQL = `VERIFIER_ANCHORED_CTE` + łańcuch CTE (`placements` z `DISTINCT ON (candidate_id, job_id)` → `person_months` → `spine` → `windows` → `senior` → `expert_months` → `expert_windows` → `expert` → `now_w`); dataclassy `frozen=True` (`SeniorityRow`, `SeniorityResult`).
- `backend/app/models/insights_seniority.py` — `InsightsSeniaoritySnapshot`.
- `backend/alembic/versions/0250_insights_seniority_snapshots.py` — `down_revision = "0249_order_rate_snapshots_offboarding"` (zweryfikuj `alembic heads` — moje statyczne skanowanie pokazało 0249 jako niereferowaną, ale w drzewie są też stare gałęzie merge'owe).
- `backend/app/tasks/insights_seniority_snapshot.py` — nocna pętla, kill-switch jako PIERWSZA instrukcja przed pętlą (lekcja CloudTalka), rejestracja w lifespan `backend/app/main.py:598-638`.
- `backend/app/api/insights_seniority.py` — `GET /api/insights/seniority` na `CurrentUser` (D7). **Bez `from __future__ import annotations`**, jeśli dołożysz `@limiter.limit` (R18, `docs/insights-dynareporter-migration-plan.md:263`).
- `frontend/src/components/insights/sections/SeniorityPath.tsx`.

**Edytowane:** `backend/app/main.py:2028` — `("insights_seniority_snapshots", InsightsSeniaoritySnapshot)` do `core_checks`; `backend/entrypoint.sh` — `CREATE TABLE IF NOT EXISTS` do `_COLUMN_STATEMENTS`.

**Progi:** z tabeli `insights_scoring_config` (wchodzi z D3 — grep potwierdza, że **jeszcze nie istnieje**), klucze `seniority_senior_short|senior_long|expert_short|expert_long`, defaulty w kodzie jak `kpi_panel.py:54-56`. **W dialogu zapisu musi stać ostrzeżenie:** poziom jest liczony, więc obniżenie progu przyznaje awanse wstecz, a podniesienie je wstecz odbiera. Ledger zapisuje przed/po.

### B.5 SQL do kalibracji progów na realnych ludziach

Uruchom PRZED zatwierdzeniem 6/12/12/24. Pokazuje, ilu ludzi wpada na każdy poziom przy każdym wariancie progu.

```sql
-- Wklej treść VERIFIER_ANCHORED_CTE (backend/app/services/kpi_panel.py:123) przed tym blokiem.
, placements AS (
    SELECT DISTINCT ON (candidate_id, job_id)
           candidate_id, job_id, credit_user,
           (reached_at AT TIME ZONE 'Europe/Warsaw')::date AS placed_on
    FROM credited WHERE stage='hired'
    ORDER BY candidate_id, job_id, reached_at ASC, credit_user NULLS LAST
)
, pm AS (
    SELECT credit_user AS user_id, date_trunc('month', placed_on)::date AS m, count(*)::int AS n
    FROM placements WHERE credit_user IS NOT NULL GROUP BY 1,2
)
, spine AS (
    SELECT b.user_id, gs::date AS m
    FROM (SELECT user_id, min(m) AS first_m FROM pm GROUP BY 1) b
    CROSS JOIN LATERAL generate_series(b.first_m, date_trunc('month', now())::date, INTERVAL '1 month') gs
)
, w AS (
    SELECT s.user_id, s.m,
           COALESCE(SUM(pm.n) FILTER (WHERE pm.m > (s.m - INTERVAL '6 month')),0)::int AS p6,
           COALESCE(SUM(pm.n),0)::int AS p12
    FROM spine s LEFT JOIN pm ON pm.user_id=s.user_id AND pm.m<=s.m AND pm.m > (s.m - INTERVAL '12 month')
    GROUP BY 1,2
)
SELECT t.p6_thr, t.p12_thr,
       count(DISTINCT w.user_id) FILTER (WHERE w.p6 >= t.p6_thr OR w.p12 >= t.p12_thr) AS osob_awansuje
FROM w CROSS JOIN (VALUES (4,8),(5,10),(6,12),(8,16)) AS t(p6_thr,p12_thr)
GROUP BY 1,2 ORDER BY 1;

-- ile placementów w ogóle jest nieatrybuowanych (to jest liczba obok sekcji):
-- ... + SELECT count(*) FILTER (WHERE credit_user IS NULL), count(*) FROM placements
--     WHERE placed_on > (current_date - INTERVAL '12 month');
```

---

## C. D7 — otwarcie RBAC na /insights

### C.0 Zasada nadrzędna: **NIE RUSZAMY `ROLE_CAPABILITIES`.**

`backend/app/analytics/capabilities.py:64-115` to jedna macierz rola→capability dla CAŁEJ aplikacji. Poszerzenie `VIEW_FINANCE` (`:47`) tam otwiera co najmniej: `analytics_v1.py:417,454,476,501,523,556`, `contractors.py:219`, `my_clients.py:233,443`, `recommendations.py:143,542,923,1599`, `prep_kit.py:179`, `user_email_templates.py:406`, `phase3_actions.py:116`, `financial_access.py:34,49` oraz redakcję w schematach `client_order.py:206,219,242`, `client_order_group.py:355,407`, `client_profile.py:44,86,123`, `contract.py:277,294,477,502`, `my_clients.py:17,49`. To wyciek stawek konsultantów i marż do wszystkiego, nie do /insights. **Zakaz.**

Realizacja D7: **własne routery `backend/app/api/insights_*.py` na `CurrentUser`**, bez redakcji. Żadnego istniejącego guardu nie poszerzamy.

### C.1 Lustra front-endu — kompletna lista

| # | Plik:linia | Stan dziś | Zmiana |
|---|---|---|---|
| 1 | `frontend/src/components/insights/InsightsView.tsx:22-36` | `TABS` — `klienci` ograniczone do `admin/HoR/DL/tac`, `zarzad` do `admin` | `roles: null` we wszystkich trzech |
| 2 | `InsightsView.tsx:40-43` | `getDefaultTabForUser` rozgałęzia się po roli | jedna wartość `"rekrutacja"`; usunąć zależność od `hasRole` |
| 3 | `InsightsView.tsx:56-59, 71-88` | `visibleTabs` filtruje + toast „Brak dostępu do tej zakładki" | `visibleTabs = TABS`; **toast i redirect zostają** dla nieznanego `?tab=` (mechanika `?tab=` jest poprawna, plan §5.0) |
| 4 | `RekrutacjaPanel.tsx:36-43` | `canSeeRanking = hasRole(...6 ról)`, użyte `:55` | usunąć zmienną i warunek; komponent renderuje się bezwarunkowo |
| 5 | `KlienciPanel.tsx:38-44` | `canSeeClientFinance` (admin), `canSeeHiringManagers` (admin/HoR), `canSeeSales` (admin), `canSeeHitRatio` (4 role); użyte `:55-59` | usunąć wszystkie cztery; `SalesOverview` znika razem z Salesem (plan §5.0) |
| 6 | `frontend/src/lib/capabilities.ts:154` | `dashboard.recruitment_stats.view: OPERATIONAL` | **NIE ruszać** — to lustro guardu `/api/dashboard/v2/recruitment-stats`, konsumowanego też przez dashboard (`RecruitmentStatsSection.tsx`). /insights ma czytać własny endpoint. Test `frontend/src/lib/__tests__/capabilities.test.ts` pilnuje domknięcia macierzy. |
| 7 | `frontend/src/middleware.ts:167-169` | `/insights` **nie ma wpisu** w `ROUTE_ROLES` → już otwarte dla każdego zalogowanego | zmiana zerowa; **dopisać komentarz** w stylu istniejącego dla `/talent-radar` (`:136-139`), żeby ktoś tego nie „naprawił" |
| 8 | `frontend/src/components/v2/shell/SidebarV2.tsx:251` | `{ href: "/insights", label: "Insights", icon: Lightbulb }` bez `roles` → otwarte | bez zmian, zweryfikować |
| 9 | `frontend/src/components/v2/shell/CommandPaletteV2.tsx:251` | wpis bez `capability` → otwarty | bez zmian, zweryfikować |
| 10 | `frontend/src/app/insights/page.tsx` | grep: brak `RequireRole` / `hasRole` | **potwierdzone czyste** — piąte lustro (in-page `RequireRole`), które ugryzło przy Talent Radarze (#1215), tutaj nie występuje |

**Test kontraktowy (obowiązkowy):** `frontend/src/components/insights/__tests__/insights-rbac.test.tsx` — renderuj `InsightsView` dla każdej z 8 wartości `UserRole` (`backend/app/models/user.py` enum: admin, head_of_recruitment, delivery_lead, finance, tac, recruiter, sourcer, user) i asertuj **trzy widoczne zakładki w każdym przypadku**. Bez tego cichy refaktor przywróci listę ról.

### C.2 Backend — promień rażenia per endpoint i decyzja

| Endpoint | Guard (plik:linia) | Konsumenci POZA /insights | Decyzja |
|---|---|---|---|
| `/api/reports/recruitment` | `require_capability(VIEW_RECRUITMENT_RANKING)`, `reports.py:191-198,200-204` | tylko wrapper `frontend/src/lib/api.ts:834` | **nie ruszać.** /insights czyta nowy `/api/insights/recruitment/funnel` |
| `/api/reports/board` | `FinanceReadUser`, `reports.py:1512-1516` | `api.ts:840` | **nie ruszać.** Nowy `/api/insights/board` na `CurrentUser` |
| `/api/reports/clients`, `/clients/at-risk`, `/clients/{id}/trend` | `_ClientsReportViewer` (admin/DL/tac/HoR), `reports.py:977-985`, użyte `:1254,1304,1372` | **`frontend/src/app/clients/[id]/page.tsx`** — profil klienta | **WSPÓŁDZIELONE → nie poszerzać.** Nowy `/api/insights/clients/hit-ratio` |
| `/api/reports/delivery-leads` (+ `/{id}/trend`) | admin+HoR, `reports.py:872-874`, `:898-900` | `api.ts:837` | **nie ruszać.** Nowy `/api/insights/delivery-leads` |
| `/api/reports/invite-links` | admin+DL+HoR, `reports.py:1760-1766` | `api.ts:842` | nowy `/api/insights/invite-links` albo przeniesienie sekcji na nowy router |
| `/api/reports/power-calling` | 6 ról, `reports.py:1877-1886` | **brak konsumenta FE** | poszerzyć do `CurrentUser` można bezpiecznie, ale **dopiero po A.1** — inaczej otwierasz listę „poniżej progu" liczoną przez 5 |
| `/api/admin/clients-overview`, `/by-dl` | `AdminUser`, `admin_clients_overview.py:112`, `:285` | **`frontend/src/lib/api/dlPortal.ts`** — portal DL | **WSPÓŁDZIELONE + admin-only → nie poszerzać.** Nowy `/api/insights/clients/mrr` czytający tę samą warstwę serwisową |
| `/api/dashboard/v2/recruitment-stats` | `OperationalUser`, `dashboard_v2.py:176` | **`RecruitmentStatsSection.tsx`, `RecruitmentTeamTable.tsx`** — dashboard główny | **WSPÓŁDZIELONE → nie poszerzać.** /insights czyta `/api/insights/recruitment/team`; docstring `:180-194` wprost ostrzega przed frontem węższym niż API — nie odwracaj tego w drugą stronę |
| `/api/competitions/current`, `/monthly-races` | `OperationalUser`, `competitions.py:38`, `:143` | `ChampionsSection.tsx` (to /insights); `/monthly-races` bez konsumenta FE | **poszerzyć na miejscu do `CurrentUser`** — jedyny endpoint, gdzie to jest bezpieczne: konsument jest wyłącznie w /insights, a `/my-position` (`:219`) już stoi na `CurrentUser` |
| `/api/phase3/reports/time-to-hire` | `RecruitmentReadAccess`, `phase3.py:394-398` | `TimeToHireSection.tsx` | plan i tak nakazuje przepisać backend (`phase3.py:428` zaniża) → nowy `/api/insights/recruitment/time-to-hire` |
| `/api/dashboard/kpis` | rozgałęzia się po `VIEW_RECRUITMENT_RANKING`, `dashboard.py:65-71` | dashboard | **PUŁAPKA: klucz cache'u rozgałęzia się po CAPABILITY, nie po userze** (`:68-71`). Nie ruszać ani guardu, ani capability — inaczej cache zaczyna serwować ranking rolom, które go nie mają. |

**Wzorzec nowego routera:**
```python
# backend/app/api/insights_board.py
# BEZ `from __future__ import annotations` — moduł ma limiter (R18).
router = APIRouter()

@router.get("/board")
async def insights_board(current_user: CurrentUser, db: Database, period: DashboardPeriod):
    """D7: /insights jest jawnie otwarte dla KAŻDEJ zalogowanej roli
    (decyzja Artura 2026-08-31, plan §0 D7). Kwoty NIE są redagowane.
    Nie zastępuj tego guardu capability — VIEW_FINANCE steruje 40+ innymi
    powierzchniami (capabilities.py:64-115) i jego poszerzenie wyciekłoby
    stawki konsultantów poza Insights."""
```
Montaż w `backend/app/main.py` obok istniejących routerów; prefix `/api/insights`.

### C.3 Co konkretnie znika z redakcji VIEW_FINANCE — i tylko tam

Na **nowych** `/api/insights/*` nie ma redakcji w ogóle. Przestaje być ukrywane:

- **Zarząd:** `revenue`, `consultant_costs`, `other_costs`, marża, `avg_margin_per_hour`, MRR 12-mies., rozbicie przychodu na klientów. Dziś za `FinanceReadUser` (`reports.py:1512-1516`).
- **Klienci:** MRR per klient i przychód roczny — dziś `AdminUser` (`admin_clients_overview.py:112`), plus jego docstring `:7` („to dane VIEW_FINANCE, HoR ich NIE ma").
- **Delivery Lead:** przychód i marża per DL — dziś `AdminUser` (`admin_clients_overview.py:285`), renderowane przez `DLRevenueLeaderboard.tsx` za `canSeeClientFinance` (`KlienciPanel.tsx:38,56`).
- **Gamifikacja:** pula nagród 5000/3000/2000 PLN — już dziś na `OperationalUser`, więc zmiana kosmetyczna.
- **Imiennie:** tabela zespołu per osoba, podium, wyścigi, „Ścieżka rozwoju" (D6) — dla `finance` i legacy `user` też.

**Co ZOSTAJE zredagowane, bo nie jest częścią /insights:** stawki konsultantów w kontraktach i zamówieniach (`schemas/contract.py`, `schemas/client_order*.py`), stawki linii MD (CLAUDE.md §Zamówienia wielo-konsultantowe), profil klienta, `/api/finance/*`, `/api/reports/{board,sales,tenders}`. Renderowanie `—` zamiast ukrywania kolumny (R14) obowiązuje tam dalej.

**Do wpisania w plan i CLAUDE.md, bo to nie jest neutralne:** pod D7 wskaźnik dzienny z mianownikiem różnym od wszystkich innych sam w sobie jest sygnałem o osobie (§A.3 pkt 2). Rekomendacja: renderować `workdays_source` jako etykietę, **nigdy** kolumny „dni nieobecności".

---

## D. Etap 0 — kontrakt okresu i kontrakt pustki

### D.1 Kontrakt okresu

**`backend/app/analytics/periods.py`**
- `:77-95` — `resolve_period(kind, *, date_from, date_to, now)` → dodać `anchor: date | None = None`. Semantyka: `anchor` = dowolny dzień W ŚRODKU żądanego okresu; `resolve_period("month", anchor=date(2026,7,15))` zwraca lipiec, nie bieżący miesiąc. Implementacja: `:122` `today = _today_warsaw(now)` → `today = anchor or _today_warsaw(now)`. Reszta gałęzi (`:124-152`) bez zmian — one już liczą od `today`.
- `MAX_CUSTOM_PERIOD_DAYS = 366` (`:27`) **zostaje** — guardrail, nie bug (R15).
- **Decyzja do zapisania w kodzie:** „Tydzień" = **poprzedni zamknięty** (jak DR, `kpi.ts:38-42`), nie bieżący do dziś (`periods.py:126-129`). W poniedziałek okno bieżące jest prawie puste. Realizacja: FE domyślnie wysyła `anchor = dziś - 7 dni` dla `kind=week`; **nie** zmieniać semantyki `resolve_period` bez anchora, bo używa jej cały `dashboard_v2`.
- Nowy `Period.cache_suffix` → `f"{kind.value}:{start.isoformat()}:{end.isoformat()}"`. Jedno miejsce, z którego każdy klucz cache'u bierze okno.

**`backend/app/api/dashboard_v2.py:113-129`** — `parse_dashboard_period` przyjmuje `anchor: date | None = Query(None)` i przekazuje dalej. `DashboardPeriod` (`:131`) bez zmian, więc wszystkie dashboardy (`:139,147,157,176`) dostają kotwicę za darmo.

**`backend/app/api/reports.py:138-149`** — `_period_start` (kroczące UTC, bez górnej granicy) **do usunięcia**; `/recruitment`, `/delivery-leads`, `/clients` przestawić na `DashboardPeriod`.

**`backend/app/api/dynareporter_rekrutacja.py:219-262`** — `_resolve_period_bounds` (inclusive end vs half-open → off-by-one-day) wycofać z użycia; nie kasować pliku (DR zostaje read-only archiwum).

**Nowy endpoint „okresy z danymi":** `GET /api/insights/available-periods` — `SELECT DISTINCT date_trunc('week', first_reached_at)` z `analytics_first_milestones` (widok: `backend/alembic/versions/0184_milestones_accepted_verification_only.py:37-62`, kolumny `candidate_id, job_id, stage, first_reached_at, first_moved_by, candidate_stage_id`; **nie jest bramkowany przez `ANALYTICS_V1_MODE`**, więc na prodzie działa). Nigdy z `dr_kpi_body_leasing` (zamrożone na tygodniu 21/2026).

### D.2 KAŻDY klucz cache'u do naprawienia

| # | Plik:linia | Klucz dziś | Wada | Akcja |
|---|---|---|---|---|
| 1 | `reports.py:211` | `reports:recruitment:{period}:{recruitment_type}` | **brak okna** — dodanie `date_from/date_to` bez zmiany klucza poda liczby jednego okna pod etykietą drugiego (R3) | `reports:recruitment:v2:{period.cache_suffix}:{recruitment_type}` |
| 2 | `reports.py:883` | `reports:delivery_leads:v2:{period}` | `period` to string enum; po kotwicy dwa różne okna dzielą klucz | `…:v3:{period.cache_suffix}` |
| 3 | `reports.py:1275` | `reports:clients:{period}:{min_closed}:{sort}:{exclude_reasons}` | jw. | `…:v2:{period.cache_suffix}:{min_closed}:{sort}:{exclude_reasons or ''}` |
| 4 | `reports.py:1317` | `reports:clients:at_risk:{period}:{drop_pp}:{min_closed}` | jw. | `…:v2:{period.cache_suffix}:{drop_pp}:{min_closed}` |
| 5 | `reports.py:1523` | `reports:board:v4-split-rate-currencies` | **stała, zero okna** — endpoint dziś nie ma okresu. Nowy `/api/insights/board` GO MA | nowy klucz `insights:board:v1:{period.cache_suffix}` |
| 6 | `reports.py:1771` | `reports:invite-links:{period}` | brak okna | `…:v2:{period.cache_suffix}` |
| 7 | `reports.py:1434` | `reports:tenders:{period}` | ta sama wada | **nie ruszać** — Przetargi poza zakresem, sekcja kasowana |
| 8 | `reports.py:417` | `reports:sales:v3-split-rate-currencies` | stała bez okna | **nie ruszać** — Sales poza zakresem |
| 9 | `kpis.py:288` | `kpis:team:panel:{kp.value}` | okno tylko przez enum | jeśli dołożysz kotwicę do `/api/kpis/team/panel` — **musi** wejść do klucza; jeśli nie dokładasz, zostaw |
| 10 | `dashboard.py:68-71` | `dashboard:kpis:v2-…:{'ranking'\|'aggregates'}` | rozgałęzienie po CAPABILITY, nie po userze | **nie ruszać ani klucza, ani guardu.** Zmiana `VIEW_RECRUITMENT_RANKING` sprawi, że cache zacznie serwować ranking rolom bez uprawnień |
| 11 | `dashboard_v2.py:1658-1661` | `dashv2:recruitment-stats:{kind}:{start}:{end}` | **POPRAWNY** | wzorzec do skopiowania w nowych routerach |

Nowe `/api/insights/*` cache'ują wyłącznie po `f"insights:{nazwa}:v{N}:{period.cache_suffix}"` — `vN` bumpujemy przy każdej zmianie formuły (inaczej stara liczba wisi TTL pod nową etykietą).

### D.3 Kontrakt pustki i awarii

Warstwa istnieje i jest dobra, ma jedną dziurę.

**`frontend/src/lib/view-state.ts:57-70`** — `resolveViewState` przyjmuje `isLoading`, a nie `isSuccess`. W przerwie między ponowieniami react-query ma `isLoading=false, isError=false, data=[]` → `isEmpty=true` → **`"empty"`**, czyli awaria renderuje się jako brak danych. Sekcje obchodzą to ręcznie, przekazując `isPending` (`ActivityHeatmap.tsx:75-76`, `FunnelSection.tsx:30-31`, komentarz w `BoardKPI.tsx:51-53`) — obejście, nie kontrakt.

Diff:
```ts
export interface ResolveViewStateInput {
  isLoading: boolean
  isError?: boolean
  error?: unknown
  isEmpty?: boolean
  /** React Query `isSuccess`. Gdy podany, "empty" wolno zwrócić WYŁĄCZNIE
   *  przy sukcesie — inaczej przerwa między ponowieniami udaje pusty wynik. */
  isSuccess?: boolean
}
// :63-69 — nowa kolejność
if (isLoading) return "loading"
if (isError || error) { /* 403 → forbidden, 404 → not_found, reszta → error */ }
if (isSuccess === false) return "loading"
if (isEmpty) return "empty"
return "ready"
```
`isSuccess` opcjonalny = zmiana niezrywająca; każde nowe wywołanie MUSI go podawać.

**`frontend/src/components/insights/sections/_shared.tsx`** — `SectionError` (`:165-193`) zostaje bez zmian, jest poprawny. Dołożyć:
- `<Degraded reason={…} />` — dla `quality != "complete"` w kopercie (wzorzec `_Quality` z `backend/app/services/dashboard_v2.py:1665`). Nie baner na górze strony, tylko **degradacja samego kafla** (R6).
- `<NotAssessable rows={…} />` — trzecia lista Power Callingu i D6 `no_data`. Renderuje powód po polsku, nigdy zera i nigdy pustego wiersza.
- `formatPLN` (`:12`) przyjmuje `number` — przy D7 nie ma czego redagować na /insights; **nie rozszerzać sygnatury o `null`**, bo to zaprosi redakcję z powrotem.

**`frontend/src/components/insights/sections/PeriodSelector.tsx`** — `Period = "today"|"week"|"month"|"quarter"` (`:5`) z etykietami „Ostatnie 7 dni" / „Ostatnie 30 dni" (`:7-12`), czyli **okna kroczące**, podczas gdy backend liczy kalendarzowo. Zastąpić `frontend/src/components/insights/PeriodPicker.tsx`: granularność (`day|week|month|quarter|year|custom`) + kotwica (strzałki ◀ ▶) + **etykieta realnego okna** („1–31.07.2026, Europe/Warsaw"). `RekrutacjaPanel.tsx:20-24` i `ZarzadPanel.tsx:11` przestawić na URL jako źródło prawdy (Rekrutacja już tak robi, Zarząd trzyma `useState` → zgub przy odświeżeniu).

**`frontend/src/lib/dashboard-presets.ts:9`** — `DashboardPeriod` dodać `"custom"`; `PERIOD_VALUES` (`:62`) i `isDashboardPeriod` (`:75-77`) zaktualizować razem.
**`frontend/src/lib/dashboard-v2-api.ts:367-376`** — `getRecruitmentStats(period)` przekazuje tylko `period`; dodać `anchor`, `date_from`, `date_to`.

### D.4 Testy Etapu 0

- `frontend/src/lib/__tests__/view-state.test.ts` — `{isLoading:false, isError:false, isSuccess:false, isEmpty:true}` → **`"loading"`**, nie `"empty"`. To jest regresja na konkretny defekt.
- `backend/tests/test_periods_anchor.py` — `resolve_period("month", anchor=date(2026,2,15))` zwraca luty 2026 (rok przestępny); `week` z kotwicą w niedzielę zwraca poprzedzający poniedziałek; DST wiosna/jesień.
- `backend/tests/test_reports_cache_keys.py` — dwa różne okna tej samej granulacji dają RÓŻNE klucze dla wszystkich pozycji 1-6 z tabeli D.2.
- `frontend/src/components/insights/__tests__/insights-rbac.test.tsx` — patrz C.1.

---

## E. Kolejność wykonania

| # | PR | Warunek wejścia | Weryfikacja | Równolegle z |
|---|---|---|---|---|
| **1** | **Power Calling — usunięcie dzielnika 5** (§A.1). Jeden plik: `backend/app/api/reports.py:1855,1967,1976-1982,1996-2004` + test | brak | `pytest backend/tests/test_power_calling_denominator.py`; `curl /api/reports/power-calling` z JWT → każdy wpis ma `per_day: null`, `meets_target: null`, jest w `not_assessable` | 2, 3, G |
| **G** | **Bramka pomiarowa D5** (§A.2, cztery zapytania). Nie kod — decyzja | dostęp do Supabase COMPASSA + JWT admina NEXUSA | wyliczone `C/N`; wynik dopisany do planu §0 przy D5 | wszystko |
| **2** | **Etap 0 backend** — kotwica w `periods.py:77-122`, `dashboard_v2.py:113-129`, usunięcie `reports.py:138-149`, klucze cache 1-6 z D.2 | 1 zmergowany (żeby nie kolidować w `reports.py`) | `pytest backend/tests/test_periods_anchor.py test_reports_cache_keys.py`; ręcznie: dwa różne miesiące pod tą samą granulacją zwracają różne liczby | 3 |
| **3** | **Etap 0 frontend** — `view-state.ts` + `isSuccess`, `_shared.tsx` (`Degraded`, `NotAssessable`), `PeriodPicker.tsx`, `dashboard-presets.ts:9`, `dashboard-v2-api.ts:367-376` | uzgodniony kontrakt z 2 (nazwy parametrów) | `npm run type-check && npm run lint`; `vitest --no-file-parallelism` (pełny suite równolegle daje losowe faile — patrz memory); Chrome MCP: wymusić 500 złym parametrem → „Nie udało się wczytać" + „Ponów", **nie** „Brak danych" | 2 |
| **4** | **Etap 1 — `insights_recruitment.py` funnel org-level** na `CurrentUser` + sekcje FE | 2, 3 | SQL kontrolny z planu §Etap 0 pkt 1 obok kafli — muszą się zgadzać | — |
| **5** | **D7 sweep** — C.1 (lustra FE) + `insights_board.py`, `insights_clients.py`, `insights_delivery_leads.py` na `CurrentUser`; poszerzenie `competitions.py:38,143` do `CurrentUser` | 4 (inaczej otwarte zakładki pokażą 403 z endpointów, których jeszcze nie ma) | `insights-rbac.test.tsx` (8 ról × 3 zakładki); Chrome MCP na koncie `sourcer` → wszystkie trzy zakładki renderują liczby, zero toastów „Brak dostępu" | 6 |
| **6** | **D6 — Ścieżka rozwoju** (§B.4): serwis + migracja `0250` + entrypoint + `core_checks` + task + endpoint + sekcja FE | 2 (okres), 5 (guard `CurrentUser`) | SQL kalibracyjny z §B.5 uruchomiony i pokazany PRZED zatwierdzeniem progów; `/api/health/deep` → `insights_seniority_snapshots` obecna | 7 |
| **7** | **D3 — `insights_scoring_config` + Liga** (plan §Etap 3) | 5 | podium stare i nowe wypisane obok siebie **przed merge'em** | 6 |
| **8** | **D5 krok 1 — PR w COMPASSIE** (endpoint push + sekret) | **G = GO** | payload nie zawiera żadnego z 16 literałów `leave_type` — asercja na stringu odpowiedzi | — |
| **9** | **D5 krok 2 — NEXUS** (scope `hr:workdays`, tabele, `compass_person_link`, przywrócenie `per_day` w Power Callingu) | 8 wdrożone | `/api/health/deep` + status syncu: liczba niedopasowanych e-maili w OBIE strony; test „5 dni nieobecności w 5-dniowym tygodniu → `not_assessable`" | — |

Równolegle bezpiecznie: **1 ∥ G**, potem **2 ∥ 3**, potem **6 ∥ 7**. Wiele PR-ów naraz → `scripts/merge-train.sh`, nie ręczne klikanie (branch protection `strict=true`, ~22 min CI). Prod ~6 min po merge'u.

---

## F. Czego NIE robimy i dlaczego

1. **Nie poszerzamy `ROLE_CAPABILITIES`** (`backend/app/analytics/capabilities.py:64-115`). `VIEW_FINANCE` steruje 40+ powierzchniami spoza Insights — to byłby wyciek stawek konsultantów, a nie realizacja D7.
2. **Nie budujemy integracji D5 przed bramką.** Pięć niezależnych faktów mówi, że pokrycie może być bliskie zeru (§A.0). Panel, który w większości wierszy mówi „brak danych o dniach roboczych", nie jest dostarczeniem.
3. **Nie pullujemy z COMPASSA na `CRON_SECRET` ani na `COMPASS_DSN`.** Pierwsze daje NEXUSOWI zdolność uruchomienia DDL na COMPASSIE (`app/api/migrate-compliance/route.ts:96-99`), drugie kładzie na drucie surowe wiersze urlopowe z typami i linkami do zwolnień.
4. **Nie portujemy `payroll-export`** (`app/api/internal/payroll-export/route.ts`) — wyklucza B2B, filtruje po nieistniejącym statusie i przesuwa daty o dzień. Liczyć w SQL na typach DATE.
5. **Nie przechowujemy `leave_type` w NEXUSIE.** Nigdy, w żadnej kolumnie, logu ani odpowiedzi.
6. **Nie zastępujemy „5" innym domyślnym mianownikiem.** Ciche 21 to ten sam defekt z większą liczbą.
7. **Nie degradujemy poziomu w D6** i **nie mutujemy w GET** — oryginał wystawiał do sześciu `UPDATE` na żądanie (`kpi.ts:4729-4869`); to jest dokładnie to, co D6 kasuje.
8. **Nie przywracamy resetu okna 12-miesięcznego** — istniał wyłącznie po to, żeby ograniczyć licznik od stałej kotwicy, której NEXUS nie ma i nie może uczciwie zmyślić.
9. **Nie ruszamy `competition_winners`** — autofreeze jest write-once (`backend/app/services/competitions.py:826-843`), nowa formuła obowiązuje od najbliższego niezamkniętego kwartału (D3).
10. **Nie robimy `DROP` na 58 tabelach `dr_*`** — memory `dr-tables-drop-classification` odradza wprost; `DYNAREPORTER_MODE=read_only` już je zamraża.
11. **Nie dodajemy tieru „ten sam localpart, dowolna domena, auto-akceptowany"** do dopasowania tożsamości — `users` zawiera obce domeny z importu Traffita (`importer.py:1425-1428`) i taki tier potrafi przypiąć urlop jednej osoby do drugiej na raporcie z nazwiskami.
12. **Nie ruszamy `dashboard:kpis` ani `capabilities.ts:154`** — klucz cache'u rozgałęzia się po capability, a nie po userze (`backend/app/api/dashboard.py:68-71`).
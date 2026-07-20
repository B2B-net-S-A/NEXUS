# Moduł 2 — niezależny re-audyt (kontra-audyt do raportu Codexa)

**Data:** 2026-07-20
**Baza kodu:** `origin/main` @ `bdf5a75` (audyt Codexa robiony był na `e25225b`)
**Cel:** znaleźć to, czego **nie ma** w rejestrze Codexa — nowe ustalenia oraz obalenia jego/własnych hipotez
**Punkt odniesienia:** `docs/candidate-talent-module-audit-and-claude-implementation-plan-2026-07-16.md` (rejestr M2-SEC/PRIV/ID/DOC/…)

---

## 1. Streszczenie

Re-audyt uruchomiony jako wieloagentowy sweep po 10 wymiarach, z adwersarialną weryfikacją każdego ustalenia i deduplikacją względem rejestru Codexa.

**Najważniejszy wynik: PR 1/7 (containment) miał lukę w powierzchniach równoległych.** Codex wyliczył w M2-SEC-01 konkretne pliki (`candidates.py`, `search.py`, dokumenty, pule, marketplace) — i dokładnie te zostały zamknięte. Ale **te same dane** kandydata serwują trzy inne routery, których nie było ani w rejestrze Codexa, ani w PR1:

- `import_export.py` — **`GET /api/export/candidates` wydawał CAŁĄ bazę** (~54k: imię, nazwisko, email, telefon, lokalizacja, stawka) **dowolnej zalogowanej roli**, bez limitu i bez audytu — czyli dokładnie to, co PR1 zamknął obok, pod inną ścieżką;
- `candidate_stage_cv.py` — rola `user` mogła **pobrać CV każdego kandydata** (oryginalne i brandowane), enumerując sekwencyjny `stage_id`;
- `candidate_pins.py` — rola `user` mogła **zbierać imię/nazwisko/email**, chodząc po `candidate_id`.

Do tego niezależnie: **nie-sekretny `revoke_key` linku CV działał jako token dostępu**, znosząc gwarancję P1.9 „sekret nigdy nie jest przechowywany".

Wszystkie cztery naprawione w PR #817 (poniżej). Dodatkowo **obalony został fałszywy P0** wygenerowany przez własny sweep — opisany w §4, bo pokazuje konkretną pułapkę metodyczną.

| | liczba |
|---|---:|
| Ustalenia potwierdzone i NOWE względem Codexa | 7 |
| Z tego naprawione (PR #817 + #819) | 5 |
| Rozszerzenia istniejących pozycji Codexa | 2 |
| **Obalone** (fałszywy P0 z własnego sweepu) | 1 |
| Niezweryfikowane (przerwane limitem sesji) | 5 |
| Wymiary bez pokrycia (agent padł) | 2 |

---

## 2. Ustalenia NOWE — potwierdzone i naprawione (PR #817)

### R-00 (P0) — równoległy eksport wydawał całą bazę kandydatów każdej zalogowanej roli

**Plik:** `backend/app/api/import_export.py`

Obok `/api/candidates/export` (zamkniętego przez PR1 na TAC+ i objętego audytem) istnieje **druga, niezależna powierzchnia**:

```python
@router.get("/export/candidates")
async def export_candidates(
    current_user: CurrentUser,          # ← gołe: każda zalogowana rola
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).order_by(...))   # ← BEZ limitu
```

CSV zawiera `name`, `lastname`, `email`, `phone`, `location`, `source`, `skills`, `salary_expectation` — czyli **cała baza ~54k kandydatów** dla roli `user` (read-only viewer/klient), którą PR1 był budowany po to, by odciąć. Bez limitu wierszy, bez zdarzenia audytowego, bez `reason/purpose`.

Bliźniaczo `POST /api/import/candidates` pozwalał tej samej roli **masowo tworzyć** kandydatów z CSV.

To jest najczystszy przykład problemu metodycznego z §6: PR1 zamknął *ścieżkę wymienioną w rejestrze*, a nie *zasób*. Dwie trasy, ten sam eksport, jedna zabezpieczona.

**Fix:** `GET /api/export/candidates` → `CandidateExportAccess` + zdarzenie audytowe (ten sam kontrakt co PR1); `POST /api/import/candidates` → `CandidateWriteAccess`.

### R-00b (P0-class) — panel generatora B2B wydawał dane kandydatów każdej roli *(PR #819)*

**Plik:** `backend/app/api/cv_generator_b2b.py`

Panel „Generator Umów B2B" jest w sidebarze **celowo dostępny dla wszystkich ról** („sourcing tooling"), a jego trasy stały na gołym `CurrentUser` — dosłownie `del current_user  # auth only`:

| trasa | co wydawała |
|---|---|
| `GET /api/cv-generator/candidates` | typeahead po imieniu/nazwisku/**emailu** po całej bazie; puste `q` = ostatnio modyfikowani. `CandidateOption` = name, lastname, full_name, position, **email** → enumeracja **bez zgadywania ID** |
| `GET /api/cv-generator/generated` | lista z `candidate_name` **cudzych** CV (`is_admin` sterował tylko flagą `can_delete`) |
| `GET /api/cv-generator/generated/{id}/docx` | **brak jakiejkolwiek kontroli własności** — 403 w tym pliku dotyczy `DELETE`, nie pobierania → dowolne wygenerowane CV kandydata po sekwencyjnym ID |

Kontrast bolesny: PR1 dał roli `user` 403 na `/api/candidates`, a ten typeahead pozwalał tej samej roli przeszukiwać tę samą bazę **razem z adresami email**.

**Fix:** typeahead → `CandidateSearchAccess`; lista + docx → `CandidateDocumentAccess`; delete → `CandidateWriteAccess`.

### R-01 (P0-class) — viewer mógł pobrać CV każdego kandydata przez router stage-CV

**Plik:** `backend/app/api/candidate_stage_cv.py`

Cztery trasy **odczytu** zostały na gołym `CurrentUser`, podczas gdy **zapisy w tym samym pliku** mają `RecruiterPlus` — autor zabezpieczył mutacje i przeoczył odczyty:

| trasa | co zwracała |
|---|---|
| `GET /candidates/stages/{stage_id}/cv/original/download` | **strumień `original_cv_content`** — surowe bajty CV |
| `GET /candidates/stages/{stage_id}/cv/original` | metadane snapshotu |
| `GET /candidates/stages/{stage_id}/cv/branded` | brandowane CV (HTML) |
| `GET /candidates/stages/{stage_id}/cv/branded/render-pdf` | to samo, printable |

`_load_csv_for_stage()` nie sprawdza własności ani widoczności, a `stage_id` to sekwencyjny int → pełna enumeracja bazy CV. To **te same bajty**, które PR1 zamknął na `/api/candidates/{id}/cv-download` i `/documents/{id}/content`.

Wektor jest realny, bo `SELF_REGISTRATION_ENABLED` pozwala założyć konto roli `user` na domenie z whitelisty.

**Dlaczego Codex tego nie znalazł:** M2-SEC-01 wylicza pliki z nazwy; `candidate_stage_cv.py` nie pojawia się w raporcie ani razu. Audyt „po liście plików" nie łapie routera, który serwuje ten sam zasób pod inną ścieżką.

**Fix:** odczyty → `CandidateDocumentAccess`.

### R-02 (P1) — viewer mógł enumerować tożsamość kandydatów przez router pinów

**Plik:** `backend/app/api/candidate_pins.py`

Cztery trasy na gołym `CurrentUser`, a `CandidatePinBrief` zawiera `name`, `lastname`, `email`, `avatar_url`. `POST /{candidate_id}/pin` przyjmuje **dowolne** `candidate_id`, więc rola zablokowana przez PR1 na `/api/candidates/{id}` mogła odczytywać tożsamość, chodząc po ID przez piny.

**Fix:** → `CandidatePIIAccess`.

> Uwaga historyczna: router pinów był sygnalizowany w całościowym audycie systemowym (2026-07-16) jako część „systemowej luki RBAC viewer poza M2", ale nie trafił do rejestru M2 i pozostał nienaprawiony.

### R-03 (P2) — nie-sekretny `revoke_key` działał jako token dostępu do CV

**Plik:** `backend/app/api/public_share.py` (`get_public_cv`)

Kontrakt token v2 (P1.9): sekret **nie jest przechowywany** — w DB tylko SHA-256, a PK dostaje jawny identyfikator `v2$<hex>` służący do **odwołania** linku. Ale dual-read dopasowywał:

```python
(CVShareToken.token == token) | (CVShareToken.token_sha256 == digest)
```

Pierwsza gałąź (dla wierszy legacy) **nie była zawężona do wierszy legacy**, więc podanie `revoke_key` w URL trafiało w wiersz v2 → dostęp do CV.

`revoke_key` jest jawny: wraca z API tworzenia tokena, jest na liście linków i **jest zapisywany do `Activity` audit log** (`details.revoke_key`). Czyli każdy użytkownik operacyjny oraz każdy z dostępem do logów trzymał działające poświadczenie do „klienckiego", bezlogowaniowego linku z CV. Klucz do *odwoływania* nie może być kluczem *dostępu*.

**Fix:** gałąź legacy zawężona do `token_sha256 IS NULL`. Zero zmian dla linków legacy i dla sekretu v2.

---

## 3. Ustalenia potwierdzone — do zaplanowania (nie w tym PR)

### R-04 (P2, NOWE) — filtr języka dopasowuje kod i poziom z **różnych** wpisów

**Plik:** `backend/app/services/structured_candidate_search.py:88`

Warunek „język EN na poziomie ≥ B2" jest budowany tak, że `code` może pochodzić z jednego elementu tablicy JSONB, a `level` z innego. Kandydat z `[{EN, A1}, {DE, C1}]` spełnia „EN ≥ B2". Wymaganie językowe faktycznie nie działa jako filtr twardy.

Codex opisał w M2-SEARCH-01 problem ogólnie („language code i level mogą pochodzić z innych obiektów JSON") — **ale jako hipotezę o kształcie danych**, nie jako potwierdzony błąd konkretnego predykatu. Tu jest zlokalizowany, konkretny warunek do naprawy.

### R-05 (P2, rozszerza M2-SEARCH-01) — paginacja bez deterministycznego tiebreakera

**Plik:** `backend/app/api/search.py:342`

Sortowanie nie ma domknięcia po unikalnym kluczu (`id`). Przy remisach w kolumnie sortowania Postgres nie gwarantuje stabilnej kolejności między zapytaniami → wiersze **gubią się lub duplikują** między stronami. Efekt rośnie po imporcie masowym, gdzie tysiące rekordów dzieli tę samą wartość (`created_at`, `updated_at`, score).

Codex zauważył problem paginacji od strony hard-capu 200 w hybrydzie; to jest druga, niezależna przyczyna tej samej klasy objawów.

### R-06 (P3, NOWE, „plausible") — blankietowy DELETE kasuje kurację manualną

**Plik:** `backend/app/services/candidate_cc_assignment.py:111`

Kontrakt „manual zawsze wygrywa" jest egzekwowany snapshotem odczytu (bail gdy istnieje wiersz `source='manual'`), ale samo usunięcie to `DELETE WHERE candidate_id = X` — **bez** zawężenia do `source != 'manual'`. Guard i delete to osobne stwierdzenia w READ COMMITTED, więc kuracja manualna zacommitowana pomiędzy nimi ginie. Okno jest wąskie, ale backfill 49k kandydatów wykonuje tę ścieżkę dziesiątki tysięcy razy.

Weryfikator obniżył do „plausible" (nie odtworzył realnego przeplotu) — **do rozstrzygnięcia przed kolejnym uruchomieniem backfillu CC**.

---

## 4. Obalone — fałszywy P0 (wartościowa lekcja metodyczna)

Sweep zgłosił, z dwóch niezależnych wymiarów, **P0: „nieuwierzytelniony path traversal → zapis dowolnego pliku"** w publicznym `/apply/{token}` (`public_share.py`, `_persist_cv`), z uzasadnieniem:

```
os.path.normpath('/app/uploads/candidate_5_../../../../tmp/evil.pdf') == '/tmp/evil.pdf'
```

Adwersarialny weryfikator **potwierdził** to ustalenie. Mimo to jest **fałszywe** — i zostało obalone empirycznie:

```
filename='../../../../tmp/evil.pdf'  → WRITE FAILED: FileNotFoundError
filename='/etc/cron.d/evil'          → WRITE FAILED: FileNotFoundError
filename='sub/evil4.pdf'             → WRITE FAILED: FileNotFoundError
/tmp/evil.pdf: exists=False          ← nic nie wyszło poza UPLOAD_DIR
```

**Dlaczego:** `os.path.normpath` jest operacją **leksykalną**, a `open()` rozwiązuje ścieżkę **przez jądro**, komponent po komponencie. Prefiks `candidate_{id}_` jest doklejany do pierwszego segmentu, więc ten segment to zawsze `candidate_5_..` albo `candidate_5_` — katalogi, które nie istnieją → `ENOENT`. Prefiks działa jako przypadkowa, ale skuteczna bariera.

**Co z tego zostaje (realne, ale drobne):** brak sanitacji nazwy pliku powoduje, że zgłoszenie z `filename` zawierającym `/` kończy się nieobsłużonym `FileNotFoundError` **po** utworzeniu rekordu kandydata → 500 i częściowy zapis. Docstring `_persist_cv` twierdzi „Mirrors `candidates.py::upload_cv`", a mirror **zgubił** sanitizer (`pathlib.Path(raw).name`). Warto wyrównać — ale to robustness (P3), nie RCE.

**Wniosek dla przyszłych audytów:** weryfikacja adwersarialna oparta na *czytaniu kodu* nie wystarcza dla ustaleń o semantyce syscalli/DB. Takie ustalenia trzeba **wykonać**. Jeden `python3 -c` obalił finding, który przeszedł przez dwie warstwy agentowej weryfikacji.

---

## 5. Niezweryfikowane (przerwane limitem sesji) — do dokończenia

Wymagają weryfikacji przed jakąkolwiek reakcją; zgłoszone przez findery, ale ich weryfikatory nie dobiegły:

| # | Ustalenie | Plik |
|---|---|---|
| U-1 | Cache match-score: `stale=False` ustawiane bezwarunkowo po wolnym recompute → wskrzeszenie unieważnionego wpisu; brak TTL i sweepera (rozszerza M2-INDEX-01) | `services/match_score_cache.py:94` |
| U-2 | Publiczny `champion-card` zwraca PII kandydata **bez** `Cache-Control: no-store` (regres vs `/cv/`) i bez rate-limitu | `api/public_share.py:60` |
| U-3 | `champion-card` i `engagement-declaration` bez throttlingu; docstring fałszywie deklaruje globalny rate limit | `core/rate_limit.py` |
| U-4 | Proxycurl: nieograniczona pętla retry na 429/503 **trzymająca** semafor klasowy → zakleszczenie całego subsystemu LinkedIn przy wyczerpaniu limitu | `services/proxycurl/client.py:127` |

**Bez pokrycia** (finder padł na limicie): wymiar **business-logic** (scoring/eligibility/marketplace) oraz **frontend XSS / utrata danych**. Tam nie twierdzę niczego — to biała plama, nie „czysto".

---

## 6. Ocena raportu Codexa

Kontra-audyt **nie obalił** żadnego z jego ustaleń — próbki, które sprawdziłem (M2-SEC-01..04, M2-PRIV-01/02, M2-SEC-03), były trafne, a PR1 potwierdził je w praktyce. Jego słabością nie są błędy, tylko **granica metody**:

1. **Inwentaryzacja po nazwach plików, nie po zasobie.** Rejestr wylicza pliki; router serwujący ten sam zasób pod inną ścieżką (`import_export`, `candidate_stage_cv`, `candidate_pins`) wypada poza radar. Stąd R-00, R-01 i R-02 — i stąd PR1, wierny rejestrowi, odtworzył tę samą lukę. Test „czy rola `user` dostaje 403 na `/api/candidates/export`" przechodził, podczas gdy `/api/export/candidates` wydawał tę samą bazę.
2. **Ustalenia ogólne zamiast zlokalizowanych.** M2-SEARCH-01 opisuje „language code i level mogą pochodzić z innych obiektów" jako ryzyko; R-04 to ten sam problem, ale wskazany co do predykatu — czyli naprawialny.
3. **Brak przeglądu powierzchni publicznych pod kątem kontraktu tokenów.** R-03 (revoke_key jako token dostępu) leży dokładnie w M2-TOKEN-01 tematycznie, ale dotyczy innego tokena niż engagement magic-link i nie został wychwycony.

**Rekomendacja do kolejnych PR-ów planu:** przed PR 2 dodać test architektoniczny „żaden router zwracający pola kandydata nie używa gołego `CurrentUser`" (grep/AST w CI). To zamyka całą klasę R-01/R-02 raz, zamiast łatać kolejne siostrzane routery po fakcie.

---

## 7. Metoda i jej ograniczenia

- 10 wymiarów finderów → adwersarialna weryfikacja per ustalenie → dedup względem rejestru Codexa.
- **Przebieg niepełny:** limit sesji ubił 12 z 25 agentów (2 findery, 9 weryfikatorów, krytyk). Ustalenia z §3 i §5 są odpowiednio: zweryfikowane / niezweryfikowane — oznaczone jawnie.
- Ustalenia bezpieczeństwa z §2 zweryfikowałem **osobiście** na `origin/main` (nie na recyklowanym worktree, który stał na przed-PR1 `e25225b` — o mało nie doprowadziło to do fałszywej diagnozy „PR1 nie zadziałał").
- §4 obalone **empirycznie**, nie przez lekturę kodu.

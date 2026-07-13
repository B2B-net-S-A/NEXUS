# Phase 16 — Edytowalny Draft Umowy w Profilu Kandydata

**Status:** ✅ Wdrożone na produkcji (2026-04-24)
**Plan:** `~/.claude/plans/zaplanuj-wszystko-zgodnie-z-ethereal-hinton.md`
**Commits:**
- backend — `b4549d9` feat(contracts): editable contract draft (backend)
- frontend — `22d4b5a` feat(contracts): editable contract draft (frontend)
- safety-net — `95e8236` fix(contracts): safety-net DDL for migracja 0058 in entrypoint.sh

## Co zostało zbudowane

Recruiter w profilu kandydata ma nową zakładkę **"Umowa"** z trzema sekcjami:

1. **Aktualna umowa** (status `active`/`ending`): card z klientem, datami, stawkami,
   marżą, trybem pracy, listą `ContractDocument` (download) + link do strony
   kontraktu.
2. **Draft do edycji** (status `draft`, jeden): pełnowymiarowy edytor Tiptap
   z renderowanym templatem Jinja, dropdown wyboru szablonu z re-renderem
   (modal potwierdzenia bo nadpisuje edycje), autosave co 2 s,
   przycisk **„Drukuj / PDF"** (browser print-to-PDF) i **„Sfinalizuj umowę"**
   (snapshot HTML jako `ContractDocument(doc_type=contract)` + status flip
   `draft → active`).
3. **Historia** (status `ended`, collapsible): tabela klient / daty / typ /
   `termination_reason`.

Dodatkowo w zakładce **„Profil"** nowa sekcja **„Dane do umowy (JDG / firma)"**
— Nazwa prawna, Forma działalności (5 wariantów), NIP, REGON, Adres siedziby.
Bez wypełnionych danych draft renderuje się z pustymi merge fields i nad
edytorem pojawia się banner ostrzegawczy z linkiem skoku do Profilu.

## Pliki

### Backend
- `backend/alembic/versions/0058_editable_draft_contract.py` — NEW; idempotentne
  ALTER TABLE dla 4 kolumn draft na `contracts`, 5 pól JDG na `candidates`,
  3 pola biz na `clients`.
- `backend/app/models/{candidate,client,contract}.py` — pola dodane
  ([candidate.py:147-158](backend/app/models/candidate.py:147), [client.py:32-36](backend/app/models/client.py:32),
  [contract.py:144-160](backend/app/models/contract.py:144)).
- `backend/app/schemas/{candidate,client,contract}.py` — `CandidateUpdate`,
  `ClientUpdate`, `ContractResponse` rozszerzone; nowe schematy
  `ContractDraftResponse`, `ContractDraftUpdate`,
  `ContractDraftFinalizeResponse`, `ContractTemplateBrief`.
- `backend/app/api/contracts.py` — 4 nowe endpointy (po
  `/{id}/activate` linia ~528):
  - `GET /{id}/draft` — lazy render z `ContractTemplate(is_default=True)`
    dla `contract_type` umowy. Persist content w bazie, activity
    `draft_initialized`. Zwraca też `available_templates`.
  - `PATCH /{id}/draft` — body `{template_id?}` (re-render) **albo**
    `{content_html?}` (zapis); 422 gdy oba lub żadne. Activity
    `draft_template_changed` / `draft_edited`.
  - `GET /{id}/draft/render-pdf` — wraps content w printable HTML
    (max-width 780px, print CSS + auto `window.print()`); browser robi PDF
    przez „Save as PDF" w dialogu drukowania.
  - `POST /{id}/draft/finalize` — walidacja `validate_ready_for_activation`
    (reuse z `_activate_contract`); snapshot HTML jako
    `ContractDocument(doc_type=contract, content_type=text/html)`; status
    flip `draft → active`; activity `draft_finalized`.
- `backend/app/api/contract_templates.py` — `_contract_vars` rozszerzone
  o pola JDG kandydata i legal entity klienta + `work_mode` /
  `office_location` na contract (templaty mają teraz pełen merge field set).
- `backend/tests/test_contracts_draft.py` — NEW; 8 scenariuszy:
  lazy render z default, idempotent GET, brak default templatu (zwraca
  empty), save edytowanego content, swap template, walidacja payloadu,
  finalize → active + ContractDocument, finalize 409 missing fields.
- `backend/entrypoint.sh` — safety-net DDL (sekcja Phase 16) — 11 idempotentnych
  ALTER TABLE/ADD CONSTRAINT chroniących prod przed `UndefinedColumnError`
  gdyby alembic upgrade nie wszedł przez multi-head dev gałąź `0036_microsoft365`.

### Frontend
- `frontend/src/lib/api.ts` — `contractsApi.draft.{get,update,finalize,printableUrl}`,
  `contractsApi.byCandidate(id)`, typy `ContractDraftResponse`,
  `ContractTemplateBrief`, `ContractDraftFinalizeResponse`.
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — nowa zakładka
  **"Umowa"** z badge `draft` gdy istnieje draft. Inline komponenty:
  - `JDGPanel` (w `ProfilTab`): edycja JDG przez `PATCH /api/candidates/{id}`,
    toast feedback.
  - `UmowaTab`: 3 sekcje (aktualna / draft / historia), banner ostrzegawczy
    gdy puste JDG.
  - `CurrentContractCard`: card summary + 4 `StatTile` (stawki, marża, mode)
    + lista `ContractDocument` z download link.
  - `DraftEditor`: Tiptap (`StarterKit`) z autosave co 2 s, dropdown wyboru
    szablonu z modalem potwierdzenia (re-render nadpisuje edycje), 2
    przyciski (Drukuj/PDF + Sfinalizuj umowę z modalem potwierdzenia).
  - `ConfirmModal`: lekki overlay potwierdzający operacje destrukcyjne.

## Verification

### Backend (lokalnie)
```bash
docker compose exec backend alembic -c alembic/alembic.ini upgrade 0058_editable_draft_contract
docker compose exec backend pytest tests/test_contracts_draft.py -v
# 8 passed in 12.10s
```

Regression test pozostałych contract testów (`test_contract_templates`,
`test_contractors_api`, `test_contracts_expansion`): **17 passed**.

### Smoke test E2E (produkcja, Chrome MCP)

Historycznie użyto wycofanego konta syntetycznego. Konto i bootstrap zostały
usunięte w ramach P0; nie należy ich odtwarzać.

1. ✅ Login → dashboard z badge „5 Aktywnych Kontraktów" (sesja zachowana).
2. ✅ Profil kandydata `Michał Wiśniewski` (id=3) → zakładka **„Profil"** →
   nowa sekcja **„Dane do umowy (JDG / firma)"** widoczna z polami Nazwa
   prawna / Forma działalności / NIP / REGON / Adres.
3. ✅ Wpisanie `Michał Wiśniewski IT Consulting` + NIP `PL5252001234` → klik
   „Zapisz" → toast „Zapisano dane do umowy".
4. ✅ Klik zakładka **„Umowa"** → trzy sekcje renderują:
   - „Aktualna umowa" → kontrakt active z klientem Bank Pekao, stawki
     20 000 / 26 000 PLN, marża 6 000.
   - „Draft do edycji" → kontrakt #12 (utworzony przez API w trakcie smoke),
     dropdown z domyślnym szablonem, label „zapisano przed chwilą przez
     wycofane konto syntetyczne" (wartość historyczna w danych testowych).
   - Tiptap edytor z lazy-renderowaną treścią szablonu, gdzie merge fields
     wstrzyknięte poprawnie:
     - **Wykonawca:** „Michał Wiśniewski prowadzący działalność pod nazwą
       **Michał Wiśniewski IT Consulting**, NIP: PL5252001234"
     - **Zamawiający:** „Nordea Bank AB · Adres: ul. Bałtycka 1, 00-001
       Warszawa"
     - **Stawka:** „**15 000 PLN** miesięcznie."
5. ✅ Tab badge `draft` (warning) widoczny przy nazwie zakładki — sygnalizuje
   pracę w toku.

### Demo data pozostawione na prod (do testów Artura)
- ContractTemplate `id=1` „Umowa B2B — szablon domyślny (smoke test)" — jeśli
  Artur nie potrzebuje, można usunąć przez `DELETE /api/contract-templates/1`.
- Contract `id=12` (kandydat 3, klient 1, status=draft) — można sfinalizować
  przyciskiem „Sfinalizuj umowę" w UI lub usunąć przez `DELETE
  /api/contracts/12`.

## Znane ograniczenia (Phase 2)

- **PDF server-side**: w Phase 1 używamy browser print (nowa karta + auto
  `window.print()`). Jeśli klient docelowo potrzebuje 1-click „Pobierz PDF"
  bez dialogu drukowania, dodać `weasyprint` do `requirements.txt` + zmienić
  `/draft/render-pdf` na zwrot `application/pdf`.
- **Aneksy (annex)**: istnieje już `ContractAmendment` API i model. W Phase
  2 dodać „Edytowalny draft aneksu" analogicznie (osobny ticket).
- **Wersjonowanie draftu**: Phase 1 — overwrite. Phase 2 — historia wersji
  w nowej tabeli `contract_draft_revisions`.
- **Uprawnienia**: wszystkie endpointy reuse `current_user`/`TacPlus` z
  `deps.py` (spójne z istniejącym `ContractsListV2`). Restrykcji per-rola
  nie dodano w Phase 1.
- **Multi-head Alembic**: w dev środowisku występuje multi-head
  (`0036_microsoft365` ↔ `0058_editable_draft_contract`). Migracja 0058
  uruchamia się explicit (`alembic upgrade 0058_editable_draft_contract`),
  na prod chronimy się safety-net DDL. Docelowo zmergować head 0036 do
  głównej gałęzi (osobny housekeeping ticket — nie blokował tego release'u).

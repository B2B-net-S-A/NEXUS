# Generator Umów B2B — completion report

**Data:** 2026-06-05
**Branch:** `claude/fervent-swanson-9f245b`

## Cel
Moduł w NEXUS generujący jednolitą umowę B2B (PL/EN, draft od 02.03.2026) z:
1. pre-fill z kandydata (JDG) + rekrutacji (klient z oferty),
2. wyborem roli z 5 kategorii (29 ról) → gotowy zakres usług w Załączniku nr 3,
3. wyjściem **DOCX** (oryginalny szablon prawny) + **PDF/podgląd** + ścieżką
   e-podpisu (Autenti) i edycji (Tiptap) przez istniejący flow draftów.

Krytyczne: zakresy obowiązków **bez znamion umowy o pracę** (art. 22 §1 KP).

## Co reużyto (nie budowano od zera)
`ContractTemplate`/`_contract_vars`/`_jinja_env`, draft `Contract` + Tiptap +
`render-pdf`, WeasyPrint, Autenti, `storage_service`, wzorzec DOCX z CV
Generatora, Competence Categories (5 kategorii).

## Zmiany — backend
- **Migracja `0123_b2b_contract_generator`** (down_revision `0122`, single-head
  potwierdzony): tabele `b2b_contract_roles` (katalog edytowalny) +
  `b2b_contract_details` (1:1 z `contracts`) + kolumna `contract_templates.language`.
- **Modele:** `B2BContractRole`, `B2BContractDetail`; relacja `Contract.b2b_detail`;
  `_contract_vars` rozszerzone o klucz `b2b` (eager-load w obu miejscach renderu).
- **Dane:** `app/data/b2b_roles.py` — 29 ról (5/6/5/7/6) z dwujęzycznym zakresem
  (4 merytoryczne + 2 wspólne bullety o niezależności). Język usługi/rezultatu.
- **Szablony:** `app/templates/contract/umowa_b2b_{pl,en}.{docx,html}` budowane
  skryptem `scripts/build_b2b_templates.py` z oryginałów (regex placeholdery na
  polach „żółtych" + paragraph-loop zakresu w Zał.3; linie podpisów zostają puste).
- **Serwis:** `services/b2b_contract_generator/` (formatting `pl_date`,
  field_mapping, docx_renderer przez **docxtpl** `autoescape=True`, seeder
  idempotentny insert-if-missing wołany w lifespan).
- **API** `/api/b2b-generator`: `GET/POST/PATCH/DELETE /roles`, `POST /generate`,
  `GET /contracts/{id}/detail`, `GET /contracts/{id}/docx`. RBAC: role katalog =
  admin, generowanie = TacPlus. `client_id` wyprowadzany z `job_id`.
- **Dep:** `docxtpl==0.20.2`.

## Zmiany — frontend
- Sidebar **Delivery → „Generator Umów B2B"** (gated `admin/delivery_lead/tac`).
- Strona `/contracts/b2b-generator` + `B2BContractGeneratorV2`:
  - krok 1: kandydat (search) + rekrutacja + język PL/EN,
  - krok 2: rola (grouped select) + edytowalny zakres (per-umowa),
  - krok 3: pola umowy (nr, daty, miasto, stawka, słownie, opis),
  - wynik: podgląd HTML (iframe) + Pobierz DOCX (PL/EN) + Drukuj/PDF +
    „Otwórz w profilu kandydata" (Tiptap + Autenti),
  - tab admin: edytor katalogu zakresów ról (bez deployu).
- `b2bGeneratorApi` w `lib/api.ts` (download przez `responseType:"blob"`).

## Weryfikacja
- ✅ `alembic heads` → single head `0123`.
- ✅ pytest `tests/test_b2b_contract_generator.py` — 11 passed (katalog ról,
  **denylista anty-„umowa o pracę"** PL+EN, render DOCX i HTML PL+EN).
- ✅ ruff check + format (app/), import smoke `from app.main import app`.
- ✅ FE `type-check` + `lint` (0 warningów w nowym pliku) + `next build`
  (route `/contracts/b2b-generator` w manifeście).
- ✅ Test renderu na danych przykładowych (DOCX PL/EN wysłane userowi do akceptacji).
- ⏳ E2E przez Chrome MCP na prod po deployu.

## Znane ograniczenia / follow-up
- `correspondence_address` zbierane i zapisywane, ale nie ma slotu w treści
  umowy (komparycja używa adresu siedziby JDG) — do dodania, jeśli potrzebne.
- „słownie" stawki: pole edytowalne (brak auto-konwersji liczba→słowa).
- Dane firmowe (NIP/REGON/adres) ciągnięte z profilu kandydata — jeśli puste,
  umowa pokaże „………"; uzupełnić profil JDG kandydata.
- Autenti dormant na prod (`AUTENTI_ENABLED=false`) — wysyłka przez profil
  kandydata zwróci graceful error do czasu aktywacji.

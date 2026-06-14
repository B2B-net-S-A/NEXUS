# Raport ukończenia — Generator Umów B2B: nazwa „B2B.net S.A." + usuwanie wygenerowanych umów

**Data:** 2026-06-14
**PR:** [#495](https://github.com/artur-t-96/Nexus/pull/495) (squash-merge → `main` `52e77a0`)
**Zgłoszenie:** dwie uwagi rekruterki do `/contracts/b2b-generator`.

## 1. Pełna nazwa spółki → „B2B.net S.A."

**Było:** w draftach umów pełna nazwa spółki = `B2B.NET S.A.`.
**Jest:** pełna nazwa = **`B2B.net S.A.`** (małe „net") we wszystkich draftach (DOCX i HTML, PL i EN).
**Bez zmian:** skrót **`B2BNET`** — termin zdefiniowany w komparycji („dalej jako «Spółka» lub «B2BNET»"), używany w całej treści (~85×).

### Co zmienione
- `backend/app/templates/contract/umowa_b2b_pl.html`, `umowa_b2b_en.html` — `B2B.NET` → `B2B.net`, także gdy nazwa rozbita na `<strong>…</strong>` (komparycja główna + komparycja DPA Zał. nr 2).
- `backend/app/templates/contract/umowa_b2b_pl.docx`, `umowa_b2b_en.docx` — zamiana **run-aware** (równej długości, mapowanie znaków z powrotem na runy → zachowane pogrubienie; nazwa w DOCX bywa rozbita na 3–4 runy, np. `B2B.` + `NET` + ` S.A.`). Po 6 zmian/plik, 0 pozostałych `B2B.NET`.
- `backend/app/services/b2b_contract_generator/clause_override_content.py` — blok podpisu w Załączniku Aliora (PL+EN).
- `backend/scripts/build_b2b_templates.py` — dodany `normalize_company_name()` (+ helper `_lowercase_net_in_paragraph`) wołany w `build()`; ponowny build ze źródeł prawnika **nie cofnie** zmiany.
- Seeder (`seeder.py`) robi UPSERT `content_jinja` z pliku HTML przy każdym deployu → nowa nazwa propaguje się do podglądu HTML w bazie.

### Świadomie pozostawione
- §7 (DPA) „Administratorem … jest **B2BNET S.A.**" (skrót + „S.A.", 1× PL + 1× EN) — zgodnie z prośbą, by skrót `B2BNET` został. Jeśli ma być tam też `B2B.net S.A.`, to dopisanie jednej reguły PL+EN (do potwierdzenia).

## 2. Usuwanie wygenerowanych umów

**Było:** zakładka „Wygenerowane umowy" tylko wyświetlała listę — bez możliwości kasowania.
**Jest:** każdy wiersz ma przycisk **„Usuń"** widoczny dla **osoby, która wygenerowała umowę** (`created_by`) lub dla **administratora**.

### Co zmienione
- **Backend** `app/api/b2b_contract_generator.py`:
  - `DELETE /api/b2b-generator/generated/{id}` — 404 gdy brak wpisu, **403** gdy nie autor i nie admin, sukces → usunięcie + wpis audytowy `Activity` (`entity_type=b2b_generated_contract`, `action=deleted`).
  - `GET /generated` zwraca teraz `id` + `can_delete` (autor lub admin) per wiersz.
- **Schema** `schemas/b2b_contract_generator.py`: `B2BGeneratedContractItem` += `id`, `can_delete`.
- **Frontend** `B2BContractGeneratorV2.tsx` (`GeneratedContractsTab`) + `lib/api.ts`: kolumna „Akcje" z przyciskiem „Usuń" (tylko gdy `can_delete`), potwierdzenie (`window.confirm`), mutacja → `invalidateQueries(["b2b-generated"])` + toast; nowa metoda `b2bGeneratorApi.deleteGenerated(id)`.

> Uwaga numeracyjna: usunięcie wpisu nie „zwalnia" numeru wstecz w sztywny sposób — sugestia kolejnego numeru = `max(numer w roku)+1`, więc skasowanie najnowszego wpisu pozwala ponownie użyć jego numeru. To log/audyt, nie rejestr nadań — zachowanie zamierzone.

## Weryfikacja
- **Backend lokalnie:** `ruff check` + `ruff format --check` OK; 16 testów B2B przeszło, w tym nowy `test_company_full_name_is_lowercase_net` (render DOCX+HTML PL/EN potwierdza `B2B.net S.A.`, brak `B2B.NET`, `B2BNET` zachowany) oraz zaktualizowany test podpisu Aliora.
- **CI (PR #495):** wszystkie checki zielone — Backend (ruff + pytest, pełna baza), Frontend (typecheck + build), Gitleaks, Trivy/hadolint, review.
- **Deploy:** `https://api.nexus.dynaminds.pl/api/health` → `version` = `52e77a0…` (zgodny z merge SHA).
- **UI (Chrome):** ⏳ niewykonane na żywo — sesja przeglądarki Artura była wylogowana (redirect na `/login`); logowania/podawania hasła nie wykonuję w imieniu użytkownika. Pokrycie zapewnione przez testy renderu (nazwa) i build FE (kolumna „Akcje"). Do domknięcia: po zalogowaniu sprawdzić wizualnie podgląd umowy (nazwa) + kliknięcie „Usuń".

## Przy okazji (poza zakresem)
- `chore: ruff format app/api/matching.py` — pre-existing dług formatowania na `main` blokował **cały** backend CI (`ruff format --check app/`). Naprawione mechanicznie (tylko zawijanie linii, bez zmian logiki), by odblokować pipeline.

## Pliki
- BE: `app/api/b2b_contract_generator.py`, `app/schemas/b2b_contract_generator.py`, `app/services/b2b_contract_generator/clause_override_content.py`, `scripts/build_b2b_templates.py`, `app/templates/contract/umowa_b2b_{pl,en}.{html,docx}`, `tests/test_b2b_contract_generator.py`, `app/api/matching.py` (format).
- FE: `src/components/v2/pages/B2BContractGeneratorV2.tsx`, `src/lib/api.ts`.

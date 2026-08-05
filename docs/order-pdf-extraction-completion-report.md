# Order-PDF extraction ("Zczytaj dane z dokumentu") — completion report

Automatyczny odczyt danych z PDF zamówienia w formularzu przedłużenia
(`ExtendOrderDialog`), plus widoczność załączonego PDF jako jednego pliku w
dwóch widokach (Dokumenty kontraktu + Pliki osoby). Funkcja opcjonalna, oddzielona
od dodania pliku i od zapisu.

## Zakres wg specyfikacji

| Pkt | Wymaganie | Realizacja |
|----|-----------|-----------|
| 1a | Dodanie PDF nigdy samo nie zmienia pól ani nie uruchamia odczytu | `onChange` inputa pliku ustawia tylko `file` + czyści baner; zero mutacji pól |
| 1b | Osobny przycisk „Zczytaj dane z dokumentu", aktywny dopiero po pliku; klik może nadpisać ręczne dane | Pomarańczowy przycisk `disabled={!file}`; `handleExtract` → `applyExtraction` |
| 1c | Mapowanie pól (numer→tytuł, start, koniec, cena netto→rate_client, total) | Prompt `ORDER_EXTRACTION` + `OrderExtractionResult` |
| 1d | Elastyczne rozpoznawanie (nagłówek/tabela/treść), format BNP `mc 06-2026_12-2026` | LLM (Claude) prymarnie + regex fallback z parserem okresu MM-RRRR |
| 1e | Baner „Sprawdź dane!" przy każdej niepewności | `uncertain` z reguł (brak pól/niska ufność/nietypowa jednostka/flaga LLM) → baner |
| 2 | Wyraźny kafelek PDF (pogrubiony, dół), pomarańczowy przycisk, pomarańczowy trójkąt ostrzegawczy | Kafelek `border-dashed` + bold; `bg-orange-500`; `AlertTriangle` `text-orange-500` |
| 3 | Jeden plik widoczny w Dokumentach kontraktu ORAZ w Plikach osoby (bez kopii) | Read-time: `OrderDocumentsSection` listuje `ClientOrder.file_path`, pobiera istniejącym `GET /orders/{id}/file`; zero kopii, zero migracji dokumentów |
| 4f | Pola zawsze edytowalne | Odczyt wypełnia tylko pola znalezione w dokumencie; wszystkie inputy edytowalne |

## Architektura (decyzje)

- **Odczyt = osobny endpoint, NIE tworzy Orderu ani nie zapisuje pliku.**
  `POST /api/clients/{client_id}/orders/extract` przyjmuje UploadFile, ekstrahuje
  tekst (temp-file, `cv_text_extractor.extract_text`, OCR fallback), woła parser i
  zwraca pola. Zapis Orderu (istniejący `POST /orders`) pozostaje bez zmian.
- **Parser**: `order_pdf_parser.parse_order_document` — prymarnie Claude
  (`call_claude`, `thinking={"type":"disabled"}` — trap Claude 5), regex fallback
  (min. okres BNP + oczywiste daty/kwoty), zawsze oznaczany jako niepewny.
- **Governance jak `cv_parser`**: nowy `AIFeatureKey.order_parser` + bramka
  `ai_quota.check_and_increment` (master → feature → miesięczny limit) + kill-switch
  `settings.ORDER_EXTRACTION_ENABLED` + model override `ORDER_PARSER_MODEL`.
- **Finance redaction**: kwoty (`rate_client`/`total_value`/`currency`) zredagowane
  dla ról bez `VIEW_FINANCE` — spójne z `_order_response_for_user`. Delivery Lead
  nie widzi i nie może przemycić kwot (lockdown zachowany, test to wymusza).
- **Jeden plik, dwa widoki (pkt 3)** — wybrano wariant **read-time inclusion**
  zamiast kopii/nowego wiersza dokumentu: dwa niezależne store'y dokumentów
  (`contract_documents` po `contract_id`, `candidate_documents` po `candidate_id`)
  nie mają mostka, a plik PO już żyje raz na `ClientOrder.file_path`. Dwa endpointy
  read-only (`/order-documents/by-contract/{id}`, `/order-documents/by-candidate/{id}`)
  listują ten sam plik; pobieranie przez istniejący `GET /orders/{id}/file`. Zero
  kopii, zero zmian w ścieżkach create/replace/delete Orderu, zero migracji dokumentów.
  Poufność: PO zawiera stawki → endpoint by-candidate filtruje po dostępie do klienta.

## Zmienione / nowe pliki

**Backend**
- `app/models/ai_feature.py` — `AIFeatureKey.order_parser` + labels/data-sent
- `alembic/versions/0214_order_parser_ai_feature.py` — enum ADD VALUE (autocommit) + seed `ai_features`
- `entrypoint.sh` — safety-net mirror (enum + seed; prod alembic bywa orphaned)
- `app/core/config.py` — `ORDER_EXTRACTION_ENABLED`, `ORDER_PARSER_MODEL`
- `app/services/llm_prompts.py` — prompt `ORDER_EXTRACTION` (v1)
- `app/services/order_pdf_parser.py` — parser (NEW)
- `app/api/client_orders.py` — endpoint `extract` + `order-documents/by-*` + finance redaction
- `app/schemas/client_order.py` — `OrderExtractionResult`, `OrderDocumentItem`, `OrderDocumentsResponse`

**Frontend**
- `lib/api/dlPortal.ts` — `extractOrderPdf`, `listContractOrderDocuments`, `listCandidateOrderDocuments` + typy
- `lib/order-documents.ts` — authed blob open/download (NEW)
- `components/ExtendOrderDialog.tsx` — kafelek, pomarańczowy przycisk, baner „Sprawdź dane!", `applyExtraction`
- `components/OrderDocumentsSection.tsx` — read-only sekcja „Dokumenty zamówień" (NEW)
- `components/ContractDocumentsTab.tsx` — render sekcji (kontrakt)
- `components/v2/files/CandidateFilesTab.tsx` — render sekcji (osoba)

## Weryfikacja

- **Backend**: `ruff check` + `ruff format --check` czyste. 31 testów w realnym
  Postgresie (image + `alembic upgrade heads`): 27 unit parsera + 4 integration
  endpointów. Migracja 0214 zaaplikowana; `ai_features.order_parser` = enabled/unlimited.
  Integration potwierdza m.in. że TEN SAM `order_id` pojawia się w widoku by-contract
  i by-candidate (jeden plik, dwa widoki) oraz że admin widzi kwoty, a złe rozszerzenie → 415.
- **Frontend**: `tsc --noEmit` — 0 błędów w plikach funkcji (jedyne 4 błędy repo to
  `ui/chart.tsx` = skew recharts 2 vs 3 z pożyczonych node_modules, plik nietknięty).
  `eslint` czysty. 15 testów Vitest: 7 `ExtendOrderDialog` (w tym separacja dodania
  pliku od odczytu, gating przycisku, baner, lockdown DL), 3 `OrderDocumentsSection`,
  5 istniejących `CandidateFilesTab` (bez regresji).
- **Adversarial review** (multi-agent, 4 wymiary → weryfikacja): patrz sekcja niżej.

## Aktywacja na prod

`AIFeatureKey.order_parser` seedowany enabled/unlimited (migracja + entrypoint).
Wymaga `ANTHROPIC_API_KEY` (już w vault) — bez niego endpoint działa na regex
fallbacku (zawsze `uncertain`). Kill-switch `ORDER_EXTRACTION_ENABLED` (default true).
Model override: `ORDER_PARSER_MODEL` (default `claude-sonnet-5`).

## Znane ograniczenia

- Odczyt stawki wpisuje surową liczbę do pola „/mc"; stawka godzinowa/dzienna z PDF
  jest flagowana jako niepewna (baner), ale nie przeliczana automatycznie — user
  weryfikuje/przelicza ręcznie.
- Sekcja „Dokumenty zamówień" w Plikach osoby jest widoczna tylko dla ról z dostępem
  do klienta danego zamówienia (PO poufne) — świadoma decyzja bezpieczeństwa.

## Adversarial review — wynik

Multi-agentowy przegląd diffu (4 wymiary: backend correctness / security-authz-finance /
spec-conformance / frontend correctness → adwersaryjna weryfikacja każdego findingu).
11 surowych findingów, 7 potwierdzonych, sprowadzają się do 4 realnych spraw — wszystkie
naprawione:

1. **[MEDIUM — naprawione] Leak metadanych finansowych** (`client_orders.py`): endpoint
   redagował WARTOŚCI kwot dla ról bez VIEW_FINANCE, ale zwracał `fields_confidence`
   (klucze `rate_client`/`total_value`… zdradzają obecność stawki) i `uncertain_reasons`
   (regułowe „Niepewny odczyt: stawka…" ORAZ swobodny tekst Claude mogący cytować kwotę)
   **bezwarunkowo**. Fix: dla `not show_finance` usuwamy klucze finansowe z confidence i
   zastępujemy powody ogólnym „Sprawdź odczytane dane przed zapisem.". Baner zostaje.
   Dodany test `test_extract_redacts_finance_and_metadata_for_delivery_lead`.
2. **[LOW — naprawione] Data EU przy submit Enterem** (`ExtendOrderDialog.tsx`): pola dat
   normalizowały EU→ISO tylko w `onBlur`; submit Enterem omijał blur → surowe „1.6.2026"
   → 422. Fix: normalizacja także w `mutationFn` przed wysłaniem.
3. **[LOW — naprawione] Synchroniczny revoke blob URL** (`order-documents.ts`):
   `downloadOrderDocument` robił `revokeObjectURL` natychmiast po `click()` (wyścig w
   części przeglądarek). Fix: odroczony revoke 60 s (jak `openOrderDocument`).
4. **[LOW — naprawione] Mylący komunikat 400 dla `.doc`**: legacy binarny `.doc` nie da
   się odczytać (python-docx) → „skan lub zaszyfrowany?". Fix: komunikat wspomina też
   „nieobsługiwany format .doc".

Odrzucone jako false-positive po weryfikacji: „DL czyta stawki z pobranego PO" (by design —
pobranie bramkowane dostępem do klienta), „leak przez listę powodów w FE" (mechanizm był
błędny; realny fix jest po stronie backendu, pkt 1), „brak invalidacji cache w zamontowanej
sekcji" (nie może zajść — dialog i sekcja nie są zamontowane równocześnie), „input pliku nie
resetuje value" (nie jest defektem w tym kontekście).

## Testy — łącznie

- Backend: **32** (27 unit parsera + 5 integration endpointów, w tym redakcja finance dla DL) —
  realny Postgres + `alembic upgrade heads`.
- Frontend: **15** (7 `ExtendOrderDialog` + 3 `OrderDocumentsSection` + 5 `CandidateFilesTab`).
- Lint/format/type-check: `ruff` + `eslint` + `tsc` (pliki funkcji) czyste.

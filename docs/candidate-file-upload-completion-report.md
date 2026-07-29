# Upload plików do kandydata — raport

**Zgłoszenie:** „Nie da się dodać pliku do kandydata. Ma być: da się dodać plik
do panelu kandydata."

**Data:** 2026-07-29

## Co było

Teczka kandydata (`candidate_documents`) miała komplet ścieżek **odczytu** —
lista, podgląd, pobieranie, presigned URL, zmiana rodzaju, ustawianie primary —
i **żadnej ścieżki zapisu z UI**:

- Backend: jedyny upload to `POST /api/candidates/{id}/cv`, który przyjmuje
  wyłącznie CV (PDF/DOC/DOCX) i **zawsze** nadpisuje primary. Certyfikat, list
  motywacyjny czy skan nie miały jak trafić do systemu inaczej niż importem
  z Traffita.
- Frontend: zakładka „Pliki i umowy" → widok „Pliki" renderowała listę, a przy
  pustej teczce wyświetlała „Brak plików. Dodaj CV lub inne dokumenty przez
  profil." — instrukcję odsyłającą do przycisku, którego nigdzie nie ma.

## Co jest

### Backend — `POST /api/candidates/{candidate_id}/documents`

Multipart (`file`, `document_kind`, `is_primary`), gate `CandidateWriteAccess`
(admin / delivery_lead / tac / recruiter / sourcer — parytet z `PATCH
/documents/{doc_id}`), odpowiedź `201` + `CandidateDocumentOut`.

Zachowanie per rodzaj:

| `document_kind` | efekt |
|---|---|
| `cv` (pierwsze CV albo `is_primary=true`) | pełna ścieżka CV: kopia na dysk (żeby legacy `/cv-download` dalej działało), ekstrakcja tekstu do `raw_cv_text`, `cv_filename`, re-embedding, wzbogacanie AI w tle |
| `cv` (kandydat ma już primary) | kolejna wersja w galerii CV, bez przejmowania primary — promocja przez istniejące „Ustaw jako primary" |
| `cover_letter` / `certificate` / `other` | sam załącznik; `is_primary=true` → 422, jak w PATCH |

Walidacja:

- rozmiar — `MAX_UPLOAD_SIZE_MB` (413), pusty plik → 400;
- **allowlista rozszerzeń** (dokumenty biurowe, obrazy, ZIP) → 415 poza listą;
- `document_kind=cv` dodatkowo zawężone do formatów tekstowych (PDF, DOC, DOCX,
  ODT, RTF, TXT) — inaczej skan JPG dałoby się ustawić jako primary CV i zabić
  ścieżkę wzbogacania profilu;
- `content_type` **wyliczany z rozszerzenia**, nie brany z nagłówka klienta.
  `/documents/{id}/content?disposition=inline` oddaje zapisany `content_type`,
  więc plik wgrany jako `skan.pdf` z podrobionym `text/html` renderowałby się
  jako HTML na originie API;
- nazwa pliku przez `pathlib.Path(...).name` — bez traversalu (ta sama wartość
  ląduje w `cv_filename`, które legacy `/cv-download` skleja z `UPLOAD_DIR`).

Deduplikacja po SHA-256 treści (istniejący mechanizm) — ponowny upload tego
samego pliku aktualizuje rekord zamiast tworzyć duplikat.

**Bez migracji** — schemat `candidate_documents` miał już wszystko. Świadomie
nie dodano `UserActionType.document_uploaded` (natywny enum w Postgresie =
migracja dla jednego wpisu leaderboardu); załącznik inny niż CV loguje się do
`Activity(action="document_uploaded")`, CV nadal do obu.

### Refaktor współdzielony

`_store_candidate_cv_document` → `_store_candidate_document` (świadome
`document_kind`, `is_primary` dozwolone tylko dla CV); stara nazwa została jako
cienki wrapper. Ciało `upload_cv` wyjęte do `_ingest_candidate_cv_file` +
`_after_cv_commit`, żeby CV dodane z zakładki „Pliki" zachowywało się **dokładnie**
tak samo jak dodane starą ścieżką (jedno miejsce zamiast dwóch kopii).

### Frontend

`PlikiTab` (346 linii wewnątrz 4,7-tysięcznego `CandidateDetailV2.tsx`) wyjęty
do `components/v2/files/CandidateFilesTab.tsx` — renderowalny i testowalny
w izolacji. Doszedł pasek uploadu: select rodzaju + „Dodaj plik" (multi-select,
upload **sekwencyjny** — równoległe zapisy ścigałyby się o ten sam wiersz przy
dedupie/primary), spinner na czas wysyłki, toast, unieważnienie cache
(`documents`, `cvDocuments`, `quickView`, `detail`).

Pasek renderuje się w **każdym** stanie listy — ładowanie, błąd, pusta teczka.
Pusty profil to dokładnie ten moment, w którym trzeba dodać pierwszy plik.
Role bez write-access nie widzą uploadu (parytet z resztą zakładki).

## Weryfikacja

- `backend/tests/test_candidate_document_upload.py` — 8 testów: listing po
  uploadzie + pobranie treści, content-type z rozszerzenia (nie z nagłówka),
  `is_primary` poza CV → 422, pierwsze CV przejmuje primary i ustawia
  `cv_filename`, obraz jako CV → 415, rozszerzenie spoza allowlisty → 415,
  pusty plik → 400, dedup po SHA, traversal w nazwie ucięty. **8 passed.**
- `test_candidate_module_access.py` — nowa trasa dopisana do macierzy write
  (viewer 403, role operacyjne przechodzą). **58 passed** razem z
  `test_route_authz_contract.py` (trasa liczona jako *gated*, baseline bez zmian)
  i `test_candidate_edit_reembed.py`.
- `frontend/src/components/v2/files/__tests__/CandidateFilesTab.test.tsx` —
  5 testów: uploader na pustej teczce, multipart z wybranym rodzajem, upload
  wielu plików + reset inputu + refetch, błąd uploadu trafia do `showError`,
  brak uploadera dla roli bez write. **5 passed.**
- `tsc --noEmit`, `eslint`, `ruff check` + `ruff format --check` — czysto na
  zmienionych plikach.

### Znane ograniczenia weryfikacji

- Pełny `pytest tests/` puszczony lokalnie w obrazie `nexus-test:fresh` na
  świeżej bazie (migracje do `heads`); CI powtórzy go na swoim postgresie.
- Lokalne `node_modules` (dowiązane z głównego repo) mają **recharts 2.15.4**
  przy `^3.8.1` w `package.json` tej gałęzi — stąd 2 błędy `tsc` w
  `ui/chart.tsx` i padający `DlTrendChart.test.tsx`, oba **niezwiązane** ze
  zmianą i nieobecne w CI (instaluje z lockfile'a). `TeamAllocationBoard` i
  `B2BContractGeneratorSignature` padają tylko przy pełnym przebiegu (timeout
  5 s pod obciążeniem), w izolacji przechodzą.
- UI nie było klikane w Chrome — gałąź nie jest zdeployowana, a lokalny stack
  frontu nie wstaje na tych `node_modules`. Zachowanie zakładki pokryte testami
  komponentowymi.

# Popraw dokument — DOCX ze śledzeniem zmian Worda (25.11.2026)

Część D planu asystenta prawnego (`docs/asystent-prawny-plan.md`, decyzje
Artura z 25.11.2026: asystent w tle istniejących ekranów, nic nie wychodzi
samo, każdy cytat sprawdza kod, dane osób do modelu tylko jako znaczniki).
Umowa przysłana przez klienta albo nasza umowa wraca jako DOCX ze śledzeniem
zmian (autor „Asystent NEXUS”) i komentarzami z powodem i podstawą.

- **Wejścia, bez osobnego modułu:** zakładka Dokumenty kontraktu — „⋯ →
  Popraw dokument…” przy pliku `.docx` i „Popraw plik z dysku” obok „Dodaj
  plik” (`components/ContractDocumentsTab.tsx`), oraz przycisk w wierszu
  rejestru umów Generatora (`GeneratedContractsTab`, plik tą samą trasą co
  „Pobierz DOCX ponownie”). Okno: `components/legal-assistant/redline/`,
  logika `lib/legal-redline.ts`, harness `/preview/legal-redline`.
- **Silnik** (`services/legal_redline/`, bez bazy): akapit = każdy `w:p`
  treści, także w tabelach (bez pól tekstowych i `mc:Fallback`). Przebieg
  dzielimy tylko na granicy zmiany z kopią `w:rPr`, skreślenie to `w:del`
  z `w:delText`, wstawka `w:ins` (nigdy w cudzym `w:ins`), nowy akapit kopiuje
  `w:pPr` kotwicy (numeracja zostaje; po nagłówku — wygląd akapitu treści).
  Komentarz w `comments.xml` (część i relacja dopisane, gdy ich nie było).
  **Pola Worda są nietykalne:** zmiana przecinająca pole albo wstawka przy nim
  → 422 z prośbą o ręczną poprawkę, bo rozcięte pole Word „naprawia”.
- **Kotwica = akapit + dosłowny fragment.** Fragment, którego nie ma albo
  który jest w akapicie kilka razy, odpada z powodem (w propozycjach modelu —
  lista „Pominięte”, przy pliku — 422 z `change_id`). Dwie zmiany na tym
  samym fragmencie = 422.
- **Propozycje modelu** (`legal_redline`, numer AP21 do nadania przy
  scalaniu): dane z kontraktu (osoba, e-mail, telefon, klient) i z wiersza
  rejestru (Partner, firma, NIP) oraz rozpoznane kodem (e-mail, konto, PESEL,
  NIP, telefon) idą jako `[PARTNER]`, `[NIP]`…; zmiana ze znacznikiem spoza
  mapy odpada (model zgadł dane). Cytat musi stać dosłownie w źródle o swoim
  `ref`; bez pokrycia → zmiana zablokowana. „Zmień” zdejmuje niesprawdzony
  cytat i blokadę — zmiana idzie pod powodem człowieka. `/render` sprawdza
  cytaty z samego dokumentu jeszcze raz i odrzuca zablokowane.
- **Bez modelu działa całość:** „Wklej poprawioną treść i porównaj” liczy
  różnice słowami (`diff.py`), awaria albo wyłączona funkcja to zdanie nad
  listą, nie pusta lista. Kod nie liczy w tym widoku terminów ani kwot —
  model ma je opisać w powodzie.
- **Bramka = pobranie dokumentu kontraktu:** sekcja Delivery,
  `AmountsViewUser`, zakres klienta Delivery Leada
  (`_assert_contract_document_client_access`), przy wierszu rejestru —
  `_load_generated_for_download`. Plik z dysku tylko z kontekstem kontraktu
  albo wiersza rejestru (z nich są nazwiska do maski). Obie trasy POST są
  w `READ_ONLY_POST_ROUTE_TEMPLATES`: niczego nie zapisują, więc werdykt jest
  literą w literę jak pobranie pliku (`tests/data/authz_golden/legal_redline.json`).
- **Zapis tylko człowiekiem:** „Zapisz w Dokumentach kontraktu” to zwykłe
  `POST /api/contracts/{id}/documents` (prawo dodawania plików, 409
  „kontrakt ma już ten plik” jak przy ręcznym uploadzie). Bez nowych tabel.
- **Fundament (część A):** do scalenia zaślepki w
  `services/legal_redline/foundation.py` (`SourcePassage`, maska, wyszukiwanie
  przepisów zwraca pustą listę). Cały kontakt z fundamentem jest w tym pliku.
- Testy: `tests/test_legal_redline_engine.py` (wstawka w środku akapitu,
  skreślenie przez trzy przebiegi, komentarz, tabela, pola, nasze wzory,
  otwarcie w `python-docx` i konwersja LibreOffice, gdy jest),
  `test_legal_redline_proposals.py`, `test_legal_redline_api.py`;
  front `lib/__tests__/legal-redline.test.ts`, `RedlineReview.test.tsx`.

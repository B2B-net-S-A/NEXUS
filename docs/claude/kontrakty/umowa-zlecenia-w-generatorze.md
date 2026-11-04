# Umowa zlecenia w Generatorze Umów — przełącznik „B2B / Zlecenie”, bez numeru, DPA opcjonalne (26.10.2026)
<!-- indeks: `POST /api/b2b-generator/mandate/render`, `contract_kind = "mandate"`, „Zlecenie z dnia …”, wzór `templates/contract/umowa_zlecenie_pl.*`, PESEL tylko w pliku, kontrakt `uzlecenie` z podpisu -->

Decyzje Artura z 26.10.2026. Do 26.10 generator wydawał wyłącznie umowę B2B;
dla zlecenia były tylko aneks, porozumienie o rozwiązaniu i puste
oświadczenia (`generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md`).
Wzór umowy przyszedł od Artura: „Umowa zlecenia” z Deklaracją Poufności
(Załącznik nr 1) i umową powierzenia danych (Załącznik nr 2), ostatnia
zmiana wzoru 04.09.2026.

- **Ten sam ekran i rejestr co B2B.** Generator → „Rodzaj umowy: B2B /
  Zlecenie” → `MandateAgreementForm.tsx`. Wiersz trafia do
  `b2b_generated_contracts` z `contract_kind = "mandate"` i jest w „Umowach
  bieżących” obok B2B. Nie zakładaj osobnego rejestru: aneks i porozumienie
  zlecenia szukają umowy właśnie tam (`document_subjects`, `parent="mandate"`).
- **Bez numeru.** Zlecenia nie mają numerów (Excel działu, aneks i porozumienie
  cytują datę zawarcia). `contract_number` = „Zlecenie z dnia DD.MM.RRRR”,
  `seq` pusty — pula numerów B2B zostaje nietknięta (`mandate.mandate_label`).
- **PESEL, dowód i adres zamieszkania tylko w pliku.** `render_payload` zapisuje
  formularz bez nich (`mandate.stored_payload`). Puste pola = kropki do
  wpisania ręcznie. „Pobierz DOCX ponownie” z rejestru wydaje plik z kropkami
  w tych miejscach — NEXUS nie ma czego wpisać.
- **DPA opcjonalne.** Przełącznik „Z umową powierzenia danych”, domyślnie
  włączony, i pole „Cel przetwarzania” (§ 2 ust. 3 DPA). Wzór miał cel pisany
  pod jedno zlecenie (platforma AI) — to tylko wartość domyślna
  (`mandate.DEFAULT_DPA_PURPOSE`, lustro `MANDATE_DPA_PURPOSE_DEFAULT` na
  froncie). Bez DPA znika Załącznik nr 2, wzmianka w § 7 i pozycja na liście
  załączników.
- **Minimalna stawka** — ta sama tabela co Płace (`payroll_rates`,
  `hr_minimum_hourly_rates`), sprawdzana dla KAŻDEGO roku okresu zlecenia
  (zlecenie XII–III podlega minimum obu lat). Rok bez minimum w tabeli = bez
  kontroli, jak w Płacach.
- **Numeracja ustępów, które cytują aneks i porozumienie zlecenia, jest
  stała:** § 2 ust. 2 (okres), § 3 ust. 1 (stawka). Nowy wzór, który je
  przesunie, wymaga zmiany `annex_mandate` w
  `build_b2b_document_templates.py`.
- **Wzór:** `templates/contract/umowa_zlecenie_pl.{docx,html}` budowany
  skryptem `backend/scripts/build_mandate_contract_template.py <wzór.docx>`
  (klocki z `build_b2b_document_templates.py`, metadane autora i dodatki
  SharePointa wycinane). Oryginału wzoru nie commitujemy (nazwiska
  w metadanych). Leży w `contract/`, nie w `documents/`: tamten katalog
  trzyma wyłącznie typy z rejestru dokumentów pochodnych (test listy plików).
- **Podpis.** „Oznacz jako podpisaną” wiersza zlecenia
  (`_ensure_mandate_employment`): kontrakt typu `uzlecenie`, od razu aktywny,
  okres umowy jako `start_date`/`end_date` (data końca jest częścią zlecenia —
  reguła „B2B bezterminowa” go nie dotyczy), stawka brutto zł/h jako
  `rate_candidate` z jednostką godzinową, bez szczegółów B2B; szkic
  zamówienia i „Zatrudniony” jak przy B2B. Warunki fill-only. Istniejący
  kontrakt innego typu tej osoby u klienta = 409 (`require_contract_type`).
- **Czego wiersz zlecenia nie ma:** „Popraw” (409 `_MANDATE_NO_CORRECTION` —
  formularz B2B nie zna zlecenia; wydaj od nowa i anuluj stary wpis), podpisu
  w NEXUSIE (`can_send_esign` false, `esign/send` 409), aneksów i dokumentów
  B2B (menu „Nowy dokument” i `_assert_parent_kind` w `b2b_documents.py`
  dopuszczają tylko dokumenty z `parent` zgodnym z rodzajem umowy — dotyczy
  też wierszy „zlecenie” z Excela). „Powiąż z kontraktem” przyjmuje tylko
  kontrakt typu zlecenie i nie zakłada szczegółów B2B.
- **Nagłówki odpowiedzi DOCX** (`X-Contract-Number`, `X-Generated-Contract-Id`)
  nie docierają do przeglądarki: globalny `CORSMiddleware` w `main.py`
  wystawia tylko swoją listę. Formularz zlecenia bierze etykietę z daty
  zawarcia, nie z nagłówka.
- Testy: `backend/tests/test_b2b_mandate_contract.py`,
  `frontend/src/lib/__tests__/b2b-mandate.test.ts`,
  `MandateAgreementForm.test.tsx`, `RegisterNewDocumentMenu.test.tsx`.

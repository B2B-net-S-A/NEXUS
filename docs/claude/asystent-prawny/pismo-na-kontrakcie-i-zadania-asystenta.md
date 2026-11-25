# Pismo na kontrakcie, zadania asystenta i `draft_legal_letter` (część F, 0789, 25.11.2026)
<!-- indeks: „Napisz pismo”, panel pisma `?pismo=`, odpowiedź na wypowiedzenie Partnera, wypowiedzenie przez nas, porozumienie, cofnięcie wypowiedzenia, nota z karą umowną, pismo do klienta, ostrzeżenie o formie, „Zatwierdzam”, folder „Pisma asystenta”, `LegalTaskRow`, `TASK_PROVIDERS`, `legal_assistant_tasks`, `/api/legal/tasks`, pasek zadań na liście kontraktów, narzędzie Jarvisa `draft_legal_letter` -->

Plan: `docs/asystent-prawny-plan.md` (część F i „Podział F / G”). Decyzje Artura
z 25.11.2026: asystent w tle istniejących ekranów, nic nie wychodzi samo,
każdy cytat sprawdza kod, terminy, daty, kwoty słownie i formy Pan/Pani liczy
kod, dane osób do modelu tylko jako znaczniki.

## Pismo na stronie kontraktu

- **Wejście:** „Napisz pismo” obok „Dodaj aneks” (kontrakt B2B, bramka jak
  Dokumenty kontraktu) i link z zadania (`/contracts/{id}?pismo=<rodzaj>`).
  Panel boczny: `components/legal-assistant/letters/LegalLetterPanel.tsx`
  (stan i zapytania) + `LetterPanelView.tsx` (widok), logika `lib/legal-letters.ts`.
- **Rodzaje** (`services/legal/letters.py`, `LETTER_KINDS`; lustro we froncie
  i w narzędziu Jarvisa pilnują testy):
  - wypowiedzenie przez nas, porozumienie o rozwiązaniu, cofnięcie wypowiedzenia
    — **kod wypełnia istniejący wzór Generatora** (`templates/documents/<typ>_pl`,
    `build_document_context`); model nie pisze ani zdania. Paragraf i okres
    wypowiedzenia we wzorze wypowiedzenia idą z PODPISANEJ umowy
    (`ref_overrides`: `notice_paragraph`, `notice_period_pl`), nie z dzisiejszego
    wzoru; bez odczytanej reguły zostaje „…” i pismo jest zablokowane. Skutki
    w kontrakcie (data końca, rejestr) daje dokument wydany w Generatorze —
    panel ma do niego link, pismo z panelu skutków nie ma;
  - odpowiedź na wypowiedzenie Partnera, nota/wezwanie do zapłaty kary umownej,
    pismo do klienta — zdania pisze `assistant.draft` (`legal_assistant`, F57).
    Nagłówek (miejsce, data), adresata, „Dotyczy” i podpis składa kod.
- **Termin** liczy `deadlines` z reguły z `termination_terms` (część E):
  „na koniec miesiąca kalendarzowego” → `notice_end_of_month` (miesiąc
  doręczenia nie wchodzi), „liczony od kolejnego miesiąca” →
  `notice_from_next_month` (dodane w tej części), dni → `term_end`. Dzień
  doręczenia = `agreement_termination_signed_on` z kontraktu (wypowiedzenie
  Partnera) albo dziś (nasze wypowiedzenie). Fakt „Rozwiązanie” porównuje
  wynik z `agreement_last_day` („zgodne z NEXUSEM” / „w NEXUSIE zapisano …”).
  Reguła nieodczytana = termin wpisuje człowiek, nie zgadujemy.
- **Do modelu tylko znaczniki:** `[PARTNER]`, `[NIP]`, `[KLIENT]`,
  `[DATA_ZLOZENIA]`, `[DATA_ROZWIAZANIA]`, `[OKRES_WYPOWIEDZENIA]`,
  `[KWOTA_KARY]` (kwota słownie z `rate_in_words`), `[TERMIN_ZAPLATY]`
  (7 dni, art. 115 KC) oraz formy grzecznościowe `[ZWROT]`, `[PAN_MIANOWNIK]`,
  `[PAN_DOPELNIACZ]`, `[PAN_CELOWNIK]`, `[PAN_NARZEDNIK]` — płeć z umowy
  w Generatorze (`render_payload.gender`), bez niej z imienia (jak umowa
  szkolenia). Polecenie dla modelu pisze kod (`letters.model_instruction`),
  prośba człowieka jest tylko dopiskiem. Nazwisko w narzędniku we wzorach =
  `partner_instrumental` z umowy w Generatorze, bez niego mianownik — kod nie
  odmienia nazwisk sam.
- **Ostrzeżenie o formie** (`letters.form_warning`): umowa z formą pisemną
  bez dokumentowej albo z doręczeniem osobiście/pocztą (bez maila), a Partner
  wypowiedział — pytanie „oryginał / podpis kwalifikowany?” z wyborem „Zamień
  na porozumienie” (ta sama data). Do odpowiedzi „Zatwierdzam” jest
  zablokowane. Przy naszym wypowiedzeniu to sama informacja (mail nie wystarczy).
- **Cytaty sprawdza kod ze źródłami z bazy, nie od ekranu**
  (`letter_service.verification_passages`): umowa i aneksy z „Aktualnej umowy”
  oraz umowy ramowe klienta pocięte na paragrafy i ustępy, przepisy z korpusu.
  `missing` / `mismatch`, pytanie o formę albo „…” we wzorze = `blocked`.
- **Akcje:** „Zatwierdzam” (`POST …/legal-letter/approve`, cytaty jeszcze raz,
  a w piśmie modelu także daty i kwoty spoza obliczeń kodu —
  `letter_service._review_issues` → `assistant.code_issues` na tekście po
  poprawkach, z wartościami kodu, nagłówkiem i „Dotyczy” jako znacznikami;
  409 przy blokadzie, to samo przy `/docx`; front odblokowuje przycisk po
  edycji, a werdykt daje serwer przy kliknięciu) → dopiero wtedy „Otwórz w oknie maila” (`SendEmailV2`
  z `defaultSubject`/`defaultBody`; treść idzie przez `plainTextToHtml`) i „DOCX
  do Dokumentów kontraktu” (`POST …/legal-letter/docx`, potem zwykłe „Dodaj
  plik” do folderu **„Pisma asystenta”**, typ `other` — szkic pisma nie może
  zostać kartą „Obowiązuje teraz”, ta sama przyczyna co folder części D).
  Pismo do klienta otwiera okno maila bez adresu (adres klienta wpisuje
  człowiek; mail zapisuje się w historii konsultanta, którego dotyczy).
- **Etykieta „do prawnika”** z `assistant.lawyer_triggers` (kara umowna, spór,
  skutek natychmiastowy); nota z karą ma ją zawsze.
- **Bez modelu** (brak klucza, awaria): pusty tekst, powód i fragmenty źródeł
  w panelu; wzory działają bez modelu w całości.

## Zadania asystenta (właściciel F)

- `services/legal/tasks.py`: `LegalTaskRow`, `TaskProvider`, `TASK_PROVIDERS`
  dokładnie jak w planie; `collect` sumuje dostawców, usuwa powtórki klucza
  i zadania zamknięte. Zadań się nie zapisuje — liczą się przy odczycie, bez
  pętli w tle.
- Tabela `legal_assistant_tasks` (0789, DDL `services/legal/tasks_schema.py`,
  lustro w `entrypoint.sh` przez `hr_schema_bundle`, sonda w `/api/health/deep`)
  trzyma tylko zamknięcia: `done` po „Zatwierdzam” (odpowiedź, porozumienie,
  cofnięcie), `dismissed` po „Pomiń”. Klucz niesie dzień wypowiedzenia —
  nowe wypowiedzenie na tym samym kontrakcie to nowe zadanie. `created_at`
  każdego dostawcy ma strefę (Europe/Warsaw); naiwna data obok `checked_at`
  zgodności dawała 500 w `merge_rows` (przegląd 25.11).
- **Dostawca F** „szkic odpowiedzi na wypowiedzenie czeka”: kontrakt B2B
  z `agreement_termination_party = consultant` i trybem `notice`, umowa
  jeszcze trwa (`agreement_last_day ≥ dziś`). Jedno zadanie na wypowiedzenie:
  dwa kontrakty tej samej osoby z tym samym dniem to jedno pismo (najnowszy
  kontrakt). Zakres = bramka treści umowy: podgląd kwot albo Moduł Finanse,
  Delivery Lead tylko u klientów z przypisania; bez tego dostawca zwraca
  pustą listę (nie 403).
- **Trasy:** `GET /api/legal/tasks[?contract_id=]`, `POST
  /api/legal/tasks/{key}/dismiss` (tylko zadanie, które pytający widzi;
  inaczej 404) — sekcja Delivery (`api/legal_tasks.py`).
- **Pasek:** `LegalTasksStrip` pod nagłówkiem listy kontraktów
  (`ContractsListV2.tsx`) i pod „Co się dzieje” na stronie kontraktu (tam
  akcja otwiera panel). Pusty stan = brak paska; błąd zapytania to komunikat
  z „Spróbuj ponownie”, nie pusty pasek. Część G dopisuje swojego dostawcę
  do `TASK_PROVIDERS`, pasek się nie zmienia.

## Bramki

`POST /api/contracts/{id}/legal-letter/draft|docx|approve` — sekcja Delivery,
`AmountsViewUser`, `_assert_contract_document_client_access` (jak pobranie
pliku dokumentu kontraktu). `draft` i `docx` są w
`READ_ONLY_POST_ROUTE_TEMPLATES` (niczego nie zapisują, jak „Popraw dokument”),
`approve` zapisuje stan zadania (zapis w Delivery). `draft` 20/min (model).
Wzorce: `tests/data/authz_golden/legal_letters.json`, `legal_tasks.json`.

## Jarvis

`draft_legal_letter` (tier `link`, sekcja Delivery, `amounts_view`, poza
`WEB_SAFE_TOOLS`): od modelu tylko `contract_id`, `kind`, prośba słowami
użytkownika i ewentualnie `penalty_amount`; dane osoby, termin i cytaty liczy
serwer tokenem pytającego (`POST …/legal-letter/draft`). Wynik to karta
„Szkic pisma — nic nie wysłano” (`JarvisLegalLetterCard`) z przyciskiem do
panelu pisma; z historii rozmowy karta ma tylko link (treść nie jest
zapisywana w rozmowie). Instrukcja w sekcji „UMOWY” promptu.

## Testy i harness

`tests/test_legal_letters.py` (wzór/model, obie generacje terminu, forma,
blokada, znaczniki, wzory wypełnione z podpisanej umowy),
`tests/test_legal_letters_api.py` (bramki, odmowy, zadania, Jarvis),
`lib/__tests__/legal-letters.test.ts`, `letters/__tests__/*`,
`jarvis/__tests__/jarvis-legal-letter.test.tsx`. Harness:
`/preview/legal-redline?widok=pismo` (osobnej strony nie ma — limit harnessów
może tylko maleć).

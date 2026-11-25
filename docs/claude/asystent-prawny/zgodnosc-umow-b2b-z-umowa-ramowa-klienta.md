# Zgodność umów B2B z umową ramową klienta w tle (część G, 0784, 25.11.2026)
<!-- indeks: back-to-back, wymogi klienta wobec podwykonawcy, DORA, szkolenia ICT, zgłaszanie incydentów, praca spoza EOG, NDA na wzorze klienta, wymiana konsultanta, prawa autorskie, dalsze powierzenie, legal_client_fit F59, legal_client_fit_checks, legal_client_fit_findings, /api/legal/client-fit, client_fit_tasks, „Sprawdzone z umową ramową”, „Dodaj do treści aneksu”, szkic klauzuli klienta, zgodnosc= -->

Plan: `docs/asystent-prawny-plan.md` (część G, „Podział F / G”). Decyzje Artura
z 25.11.2026: asystent działa w tle istniejących ekranów, nic nie wychodzi
samo, każdy cytat sprawdza kod. Pytanie, na które odpowiada: czy nasze umowy
z Partnerami przenoszą wymogi, które klient stawia nam w umowie ramowej
i aneksach (np. aneks DORA) — i ile aktywnych umów B2B tego klienta to dotyczy.

## Decyzje, które łatwo cofnąć „przy okazji”

- **Ustalenie bez pokrycia odpada.** Model wskazuje fragment klienta (`K…`)
  i paragraf naszego wzoru (`T…`) z cytatem; `engine.quote_verified` sprawdza
  każdy cytat `citations.verify` z tekstem wskazanego fragmentu. Cytat
  klienta jest wymagany zawsze, nasz — przy `ok` i `decide` (CHECK
  `ck_legal_client_fit_findings_our_side` w bazie). Luka (`gap`) może mieć
  „brak w naszej umowie”. Nie dopuszczaj „ok” z samego zdania modelu.
- **Oznaczenia liczy kod**: paragraf i ustęp klienta z układu całego
  dokumentu (`contract_document_text.structure`), § naszego wzoru z nagłówków
  szablonu; następny krok z katalogu tematów (`topics.py`), nie z modelu.
- **Treść do aneksu** (`annex_text`) odpada, gdy ma liczbę, której nie ma
  w cytacie klienta, albo znacznik danych spoza mapy. Liczba w nazwie
  („B2BNET”, „ISO 27001”) liczbą nie jest.
- **Bez modelu nic nie udaje zgodności.** Brak klucza, wyłączona funkcja albo
  limit → status `unavailable`, awaria → `failed`; ekran pokazuje „Sprawdzenie
  niedostępne”, zadania milczą, a ustalenia z poprzedniego udanego biegu nie
  są pokazywane (`service.SHOWS_FINDINGS`).
- **Treść umów klientów idzie do modelu** (decyzja z 09.10.2026), **dane osób
  nie**: kontakty klienta jako `[OSOBA]`, do tego automat maski (e-mail,
  telefon, NIP, PESEL, rachunek). Z naszego wzoru odpada komparycja przed § 1,
  pola Jinja zostają jako „…”.
- **Szkic klauzuli klienta do nowych umów** to wyłącznie zgłoszenie
  (`clause_draft_*` przy ustaleniu, lista `GET /api/legal/client-fit/clause-drafts`
  dla administratora). `clause_overrides` zmienia programista po akceptacji
  treści przez Artura (reguła z `kontrakty/aneks-z-wlasna-nazwa.md`: nowa
  treść prawna wymaga akceptacji).

## Co jest porównywane

- **Klient:** umowy ramowe bez wygasłych, rozwiązanych i zastąpionych oraz ich
  aneksy — tylko z aktualną treścią w indeksie (`framework_contract_index`).
  Dla każdego tematu dwa najlepsze fragmenty (słowa + znaczenie), łącznie do
  36 tys. znaków.
- **Nasz wzór:** `templates/contract/umowa_b2b_pl.html` z klauzulami klienta
  (`clause_overrides.resolve_override` po nazwie, nazwie prawnej albo
  wyświetlanej) — te same operacje co przy generowaniu. Wariant spółki i wzór
  EN nie są porównywane osobno.
- **Tematy** (`topics.TOPICS`, klucz = klucz ustalenia): szkolenia ICT/DORA,
  zgłaszanie incydentów, lokalizacja danych i praca spoza EOG, NDA na wzorze
  klienta, wymiana konsultanta z uprzedzeniem, prawa autorskie, dane osobowe
  i dalsze powierzenie, prawo audytu. Nowy temat = wpis w katalogu (bez
  migracji).
- **Liczba umów:** aktywne kontrakty B2B klienta (`active`, `ending`) — luka
  we wzorze dotyczy każdej z nich. Treści podpisanych umów Partnerów (część E)
  ta część nie czyta.

## Kiedy biegnie i jak się zapisuje

- Po odczycie wgranej albo podmienionej umowy ramowej lub aneksu
  (`framework_contract_index.index_contract` / `index_amendment` →
  `service.after_document_indexed`) i na żądanie („Sprawdź ponownie”,
  `POST …/check`). Bieg po wgraniu pomija klienta, gdy odcisk źródeł (pliki,
  ich czytelność, wzór z klauzulami) jest ten sam co przy ostatnim wyniku;
  dojście wektorów do już przeczytanego pliku nie zmienia odcisku.
- Jeden bieg naraz na klienta w procesie, zlecenie „w kolejce”/„trwa” młodsze
  niż 15 min nie zakłada drugiego. Bez pętli w lifespanie (wpis w
  `app/core/staging.py` niepotrzebny).
- `legal_client_fit_checks` — wiersz na klienta; `legal_client_fit_findings` —
  `UNIQUE (client_id, topic)`: ponowne sprawdzenie nadpisuje ustalenie tematu
  (to samo `id`), temat, którego już nie ma, znika. DDL w `schema.py`, lustro
  w `entrypoint.sh` przez `hr_schema_bundle`, sondy w `/api/health/deep`.
- Scalanie duplikatów klientów przepina wiersze po kluczu obcym; dwa
  duplikaty, oba ze sprawdzeniem, zatrzymają scalenie na `UNIQUE` (zatrzymanie
  z powodem, nie cicha utrata) — wtedy usuń wiersz `legal_client_fit_checks`
  duplikatu i sprawdź klienta ponownie.

## Dostęp

- Trasy `/api/legal/client-fit/clients/{client_id}` (GET, POST `/check`) stoją
  za `LegalDocsReader` — jak treść umów ramowych: sekcja Delivery, „Stawki
  i kwoty: podgląd” u klienta z zakresu, Delivery Lead u klientów
  z przypisania. Szkic klauzuli: `LegalDocsWriter`. Lista szkiców: admin.
  Wzorzec: `tests/data/authz_golden/legal_client_fit.json` (litery GET = litery
  `framework-contracts/search`).
- Dostawca zadań `task_provider.client_fit_tasks(db, user)` pilnuje tego samego
  zakresu sam (sekcja Delivery, `amounts_view`, portfel DL); jedno zadanie na
  klienta, klucz `client_fit_gap:<id>:<chwila sprawdzenia>` (przegląd 25.11:
  „Pomiń” wycisza tylko to sprawdzenie, nowe z luką wraca), link do kreatora aneksu
  `/contracts/b2b-generator?tab=annexes&new=annex_custom&zgodnosc=<id>`.
  `LegalTaskRow` to lokalna kopia (TODO scalania), rejestrację w
  `TASK_PROVIDERS` robi sesja scalająca; G nie zmienia `ContractsListV2.tsx`.

## Ekrany

- Kreator „Nowy aneks” (krok formularza) i „Nowa umowa” (pod polem klienta):
  zwijany panel „Sprawdzone z umową ramową <klient> i przepisami”
  (`components/legal-assistant/client-fit/ClientFitPanel.tsx`) z lukami,
  cytatami, jedną pozycją „ok” i przyciskiem „Dodaj do treści aneksu” (tylko
  aneks z polem `annex_changes`, wiersz „własny tekst”). Klient z prefillu
  (`client_id` w `GET /documents/prefill`) albo z wyboru osoby. 403 = panel
  się nie pokazuje (rekruter bez podglądu kwot), inna awaria = komunikat
  z „Ponów”.
- Okno szczegółu (tabela temat / wymaga klient / nasza umowa / stan / krok):
  z zadania (`?zgodnosc=`) i z karty klienta → Umowy („Zgodność umów B2B”).
  Bez nowej pozycji menu i bez trasy `/legal`.
- Harness: sekcja w `/preview/legal-redline` (limit stron harnessów).

## Funkcja AI

`legal_client_fit` (F59) — Sonnet 5.5 z zapasem Sonnet 5, jak F58 (proza
prawnicza z cytatami), bez osobnego pomiaru; env `LEGAL_CLIENT_FIT_MODEL`,
prompt `llm_prompts.LEGAL_CLIENT_FIT`. Zmiana modelu po pomiarze na modelu
z produkcji.

## Testy

`tests/test_legal_client_fit.py` (bez bazy: cytaty, odrzucenia, maska,
brak modelu, wzór, odcisk, bramki, zakres zadań), `test_legal_client_fit_db.py`
(CI: brak duplikatów, jedno zlecenie, „niedostępne” bez ustaleń, zadania DL),
front `lib/__tests__/legal-client-fit.test.ts`,
`components/legal-assistant/client-fit/__tests__/ClientFitPanel.test.tsx`.

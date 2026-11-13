# E-faktury Peppol z faktur w KSeF (plan Nordei N2, 13.11.2026)

<!-- indeks: services/peppol, UBL BIS 3 z FA(3), Schematron w osobnym procesie, budżet KSeF pętli sprzedaży, tryb testowy, dostawca z API -->

Decyzje Artura z 13.11.2026: NEXUS robi z faktury w KSeF e-fakturę Peppol BIS
Billing 3 (format bazowy, walidowany przed wysyłką). Doręcza ją najpierw
kanałem bezpośrednim do Vismy Nordei (Proceedo), a zapasowo przez dostawcę
Peppol z API. Bez własnego punktu dostępu (członkostwo OpenPeppol i
certyfikacja to kilka tysięcy euro rocznie) i bez płatnej integracji EBI24.
Faktury do Nordei zostają per konsultant (uzgodnione z Nordeą). Opis etapu: `docs/rozliczenia-nordea-n2-peppol.md`.

- **Źródło to XML z KSeF, nie PDF ani EBI24.** Pętla faktur sprzedażowych
  (`client_invoicing/sync.py`) oddaje pobrany plik do `peppol.service.capture`
  bez dodatkowego zapytania. Zaległe faktury doczytuje `backfill_xml` z resztki
  budżetu tej pętli (najwyżej 10 na przebieg) i tylko przy włączonym module
  rozliczeń. Limit Płac (8 zapytań i 40 pobrań na godzinę) zostaje nietknięty.
  Skrót pliku musi się zgadzać z `client_sales_invoices.xml_sha256`.
- **E-faktura różna od faktury w KSeF nie wychodzi.** Konwerter (`peppol/ubl.py`)
  porównuje sumę pozycji z netto (`P_13_*`), VAT i brutto z fakturą. Stawki,
  których nie znamy (zwolnienia, 0%), odrzuca zamiast zgadywać kod.
- **Reguły EN16931 i Peppol biegną w osobnym procesie** (`peppol/validation.py`).
  SaxonC wywołany z innego wątku niż ten, który utworzył procesor, kończy cały
  proces (`StackOverflowError`, zmierzone 13.11.2026 przy `asyncio.to_thread`).
  Nie przenoś walidacji do wątku ani do procesu web. Nowe wydanie reguł Peppol:
  `backend/scripts/build_peppol_rules.py`, potem `tests/test_peppol_ubl.py`.
- **Tryb testowy jest domyślny.** Każda wysyłka idzie na adres testowy odbiorcy,
  a Finanse przełączają na produkcję w ustawieniach ekranu (z potwierdzeniem),
  bo e-faktury w Vismie Nordei nie da się anulować. Wysyłka testowa nie zamyka
  faktury w trybie produkcyjnym. Testowe adresy Nordei są w produkcyjnej sieci
  Peppol (katalog 13.11.2026), więc piaskownica dostawcy podłączona do sieci
  testowej Peppol do nich nie sięga.
- **Jedna faktura = jedna wysyłka.** Wiersz przechodzi w `sending` (commit)
  przed wywołaniem dostawcy, pod blokadą i ze świeżym odczytem — drugie
  „Wyślij” albo automat go nie weźmie (13.11.2026 test z dwoma równoległymi
  żądaniami dawał 3 wysyłki na 2 faktury). Przerwana odpowiedź albo 5xx po
  wysłaniu zostawia `sending` („Wysyłka niepewna”): automat jej nie ponawia,
  osoba może wysłać ręcznie po 10 minutach i sprawdzeniu u dostawcy. Recommand
  nie ma klucza idempotencji przy wysyłce.
- **VAT i brutto z KSeF, bez tolerancji.** VAT per stawka idzie z `P_14_x`
  (w korekcie VAT-y przed i po są zaokrąglone osobno), a różnica brutto o grosz
  blokuje wysyłkę.
- **Automatyczna wysyłka tylko po włączeniu przez Finanse** (`auto_send`
  w `app_settings['peppol_einvoices']`).
- **Kanał przez adapter** (`peppol/providers.py`). `visma_direct` ma tylko
  nazwę i powód wyłączenia, dopóki technik Vismy nie poda kanału (cXML
  Proceedo albo OIO UBL przez HTTPS/SFTP, adres, uwierzytelnienie, test).
  Nie implementuj go bez tej specyfikacji. Klucz i sekret tylko
  workflow „Coolify set env” (`PEPPOL_API_KEY`, `PEPPOL_API_SECRET`,
  `PEPPOL_COMPANY_ID`, `PEPPOL_PROVIDER`, `PEPPOL_SENDER_ID`). Staging i testy:
  `PEPPOL_PROVIDER=simulate`.
- **Odbiorcy po numerze VAT z faktury** (`FI28583949`, `PL…`), adresy z katalogu
  Peppol. Podmiot bez adresu w danym trybie = faktura czeka (`waiting_receiver`).

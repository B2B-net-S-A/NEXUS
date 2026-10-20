# Zgody na wydatki i premie poza umową (0483, 20.10.2026)

Artur zatwierdzał mailem („approved”) premie poza umową, subskrypcje,
delegacje, prezenty i szkolenia. Decyzja 20.10.2026: robimy to w NEXUSIE.
Kafelek ma zakładkę „Zgody” w „Ludzie → Akceptacje”, obok urlopów
i timesheetów. Pasek dostaje ikonę „Zgody” tylko u osób, które zatwierdzają.
Do decydującego idzie mail z kwotą i przyciskami. Odpowiedź „approved” na
maila to kolejny etap. Makiety: https://claude.ai/artifact/BMmUXqykCRrfcocgPfHChj.

- **Premie z umowy nie przechodzą przez zgody.** Placementy, ligi i reguły
  Płac liczą się same (automat premii). Zgoda to tylko to, czego nie ma
  w umowie ani w regułach: premia uznaniowa, nagroda, wyjątek, wydatek.
- **Tabela `approval_requests`** (`services/hr_approvals_schema.py`, model
  `models/hr_approval.py`). Rodzaje: `bonus`, `subscription`, `trip`,
  `gift`, `training`, `other`. Stany: `pending_supervisor`,
  `pending_final`, `approved`, `rejected`, `returned` (pytanie do autora —
  poprawia i wysyła znowu, `PUT`), `withdrawn`. Premia ma osobę i miesiąc
  wypłaty, jest raz i brutto (CHECK `bonus_shape`). Nikt nie decyduje we
  własnej sprawie ani o premii dla siebie — CHECK w bazie i 403 w serwisie.
- **Droga** (`services/hr/approvals/service.py`, `route`):
  - Premia: prosi Płace albo przełożony osoby
    (`PayrollViewer.manages_bonuses_of`). Wniosek przełożonego to jego
    poparcie, więc idzie prosto do zatwierdzającego.
  - Wydatek: najpierw przełożony autora (`recipients.supervisor_of`,
    przełożony z kartoteki albo head pionu). Kadry jako zapas się nie liczą,
    bo Kadry nie decydują o wydatkach. Do progu przełożony zatwierdza sam,
    ponad próg jego „Zatwierdź” to poparcie i sprawa idzie do
    zatwierdzającego. Inną kwotę ustala tylko decyzja zamykająca sprawę.
    Autor bez przełożonego (zarząd) trafia od razu do zatwierdzającego.
  - Zatwierdzający decyduje na każdym etapie.
- **Zasady** `app_settings['hr_approval_rules']`
  (`services/hr/approvals/rules.py`, `GET/PUT /rules`, tylko admin):
  - `final_approver_user_id` — puste albo nieaktywne konto = aktywni admini;
  - `supervisor_limits[rodzaj]` — brutto w PLN, `null` = nigdy. Domyślne
    progi z makiety: premia i subskrypcja `null`, delegacja 1500, prezent
    200, szkolenie 1000, inny 500.
  - Do progu liczy się: netto ×1,23, co miesiąc ×12, inna waluta = zawsze
    zatwierdzający (w NEXUSIE nie ma kursów).
- **Po zatwierdzeniu premii** powstaje przyznana premia w Płacach:
  `hr_bonuses`, `source='manual'`, kategoria „Inna”, `proposed_by` = autor,
  `assigned_by` = zatwierdzający, `rule_snapshot.approval_request_id`.
  Płace jej drugi raz nie zatwierdzają. Zamknięty miesiąc wypłaty = 409
  i zgoda zostaje do decyzji. Miesiąc wypłaty mieści się w oknie od
  poprzedniego do dwóch kolejnych. Kontekst decyzji („NEXUS sprawdził”,
  `context_for`) rozdziela premie osoby w roku na automatyczne, poza umową
  (z `approval_request_id`) i inne ręczne.
- **Dzwonki i mail.** `hr_approval_requested` idzie do decydującego na
  danym etapie: przełożony albo zatwierdzający, nigdy oba naraz.
  `hr_approval_decided` idzie do autora. Oba mają temat `other` (dymek)
  i mail „Czas i ludzie”.
  - Mail do decydującego składa `services/hr/approvals/mail.py`, z kwotą,
    „po co” i przyciskami. To świadomy wyjątek od `hr_mail.py`, który kwoty
    wycina.
  - Przyciski otwierają NEXUS na zgodzie z `&decide=approve|reject`.
    Decyzję potwierdza się tam, z samego maila nic się nie zatwierdza.
  - Zgoda już rozpatrzona albo u kogoś innego nie daje maila.
  - Mail do autora nie niesie uwagi decydującego (wolny tekst).
- **Moduł `approvals`** w `hr_modules` jest domyślnie wyłączony (admin widzi
  ekrany zawsze). Bramka `require_hr_approvals`, trasy
  `/api/hr/approval-requests` za wyłącznikiem programu. Licznik zakładki to
  `consents` w `GET /api/hr/counts`, osobno od `approvals` (urlopy
  i timesheety).
- **Poza etapem 1** (nie dopisuj „przy okazji”):
  - zatwierdzenie odpowiedzią „approved” (czytnik skrzynki) — etap 2,
  - zastępca zatwierdzającego w czasie urlopu.

## Etap 3 — rozliczenie w Finansach (0485, decyzje Artura 20.10.2026)

Makiety: plansze 4 i 5 w https://claude.ai/artifact/BMmUXqykCRrfcocgPfHChj.
Schemat `services/hr_approval_settlement_schema.py`, serwis
`services/hr/approvals/settlement.py` (+ `cost_invoices.py`, `finance_views.py`,
`reader.py`, `store.py`), trasy autora w `api/hr_approvals.py`, Finanse
w `api/hr_approval_finance.py` (`/api/finance/approved-expenses`).

- **Decyzje Artura (20.10.2026):**
  - faktura z KSeF pasująca do zgody przypina się sama, ale „Rozliczone”
    klika osoba z Finansów — automat niczego nie rozlicza;
  - „Wydatki ze zgodą” widzi uprawnienie „Moduł Finanse” (`FinanceModuleUser`)
    i admin; premie poza umową są tam tylko sumą miesiąca, bez osób
    (szczegóły premii zostają w Płacach, D2); premia nie ma rozliczenia;
  - do „Faktur bez zgody” trafia każda niedopasowana faktura kosztowa;
    Finanse oznaczają sprzedawcę jako „stały koszt” (`approval_fixed_cost_sellers`)
    i jego faktury przestają wpadać do kolejki (obecne przechodzą od razu);
  - faktury kosztowe zapisujemy **z samych metadanych KSeF** (sprzedawca,
    numer, data, kwoty), bez pobierania XML-a i bez pozycji — limit pobrań
    zostaje dla faktur kontraktorów.
- **Rozliczenie zgody** (`approval_requests.settlement_status`, ustawia
  `settlement.on_approved` w `decide`): wydatek raz `open` → `documented` →
  `settled`; bez dokumentu przez 30 dni od zatwierdzenia → `expired`
  (pętla `hr_lifecycle` od 8:00, dzwonek do autora, potem nowa zgoda);
  cykliczny (subskrypcja, „co miesiąc / co rok”) `active` → `ended`, każda
  faktura rozliczana osobno; bez żadnego dokumentu przez 30 dni od startu
  (`starts_on`, gdy jest późniejszy niż zatwierdzenie) też `expired` — nic nie
  kupiono, więc rejestr nie liczy „wiszącej” kwoty. Zatwierdzone przed 0485
  dostają rozliczenie w migracji.
- **Dokumenty** (`approval_documents`): autor albo Finanse wgrywają PDF/JPG/PNG
  do 10 MB (`store.py`, podkatalog `approval_documents/<zgoda>/` — nie e-teczka,
  bo to papier firmy). Odczyt kwoty, waluty, NIP-u i sprzedawcy robi model
  z rejestru (`expense_document_read`, F32) — to podpowiedź, osoba poprawia
  pola (`PATCH`), awaria albo brak limitu AI zostawia dokument bez odczytu.
  Kwoty i NIP sprzedawcy faktury z KSeF są wiążące (409 przy poprawce). Ta sama faktura wgrana
  i z KSeF (NIP + numer) to jeden wiersz.
- **Dopasowanie KSeF** (`settlement.match_document`): zgoda zatwierdzona,
  otwarta, ten sam NIP sprzedawcy (z formularza, z odczytu pliku albo z
  pierwszej przypiętej faktury) i waluta, prośba nie później niż 30 dni po
  wystawieniu faktury. Kilka takich zgód — wygrywa jedyna, w której kwota się
  mieści, inaczej kolejka (`several`). Korekty idą do kolejki. Najpierw zgoda,
  potem „stały koszt”. Ręczne przypięcie zapamiętuje NIP przy zgodzie, więc
  następna faktura subskrypcji przypina się sama. Nowa zgoda z NIP-em próbuje
  przypiąć faktury z kolejki (`rematch_seller`). Pobieranie: `ksef/sync.py`
  `_store_cost`, licznik `costs` — tylko przy włączonych modułach „Rozliczenia”
  (pętla KSeF) i „Zgody” oraz tokenie KSeF.
- **Próg 10%**: wydatek raz porównuje sumę dokumentów, cykliczny — każdą
  fakturę z kwotą zgody (podstawa netto/brutto ze zgody; inna waluta albo
  brak kwoty = porównuje człowiek). Ponad zgoda + 10% + zatwierdzone dopłaty
  = „Poproś o dopłatę” (autor albo Finanse, jeden przycisk) → dzwonek
  `hr_approval_topup_requested` do zatwierdzającego, decyzja w
  „Akceptacje → Zgody” (`GET /topups`, licznik `consents`) i dzwonek do autora.
  „Rozliczone” przy fakturze ponad próg bez dopłaty = 409; po odrzuconej
  dopłacie Finanse rozliczają z obowiązkową notatką.
- **Nikt nie rozlicza własnego wydatku** (403); autor nie decyduje o swojej
  dopłacie.
- **Subskrypcje**: rejestr z zatwierdzonych zgód cyklicznych; roczna ma
  `renews_on` (rocznica startu albo zatwierdzenia). 30 dni przed odnowieniem
  opiekun (autor) dostaje raz `hr_subscription_renewal` i odpowiada
  „Dalej potrzebna” / „Wyłącz” (`POST /{id}/renewal`); minione odnowienie bez
  odpowiedzi przesuwa się o rok. Poranny skrót zatwierdzającego i Finansów
  ma linię „Odnowienia roczne subskrypcji w ciągu 30 dni” (admin bez ról
  ze skrótu go nie dostaje — `DIGEST_ROLES`).
- **Prezent dla klienta**: pole klienta tylko przy prezencie (422 przy innym
  rodzaju); po zatwierdzeniu wpis `client.gift` w Historii zdarzeń klienta
  (`critical_events`, z kwotą i numerem zgody).
- **Delegacja**: po zatwierdzeniu dni robocze `starts_on`–`ends_on` autora
  (z kartoteką) dostają obecność `business_trip`; dzień urlopu zostaje urlopem;
  delegacja dłuższa niż 62 dni nie trafia do obecności (pomyłka w datach).
- **Poza etapem 3**: „Zapytaj, kto kupił” przy fakturze bez zgody, „nieużywane
  60 dni” przy subskrypcji, sprzęt z zakupu w module Sprzęt.

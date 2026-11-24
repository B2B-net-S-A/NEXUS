# CPro Nordei na wsparcie@ — koniec, nieprzedłużenie, internalizacja, przedłużenie, zmiany do faktury
<!-- indeks: noreply@onevms.se, nordea_cpro, nordea_cpro_case, CPro, Contract terminated, will not be extended, internalization, internalizacja, You have N contract extensions to handle, prolongation, Important changes made to contract, Invoice address, nabywca Nordei, cost center, NIIDS, line manager, End day, exit_last_day, cpro_event, cpro_recruitment, Benefity, rezygnacja do 19., Sprzęt do zwrotu z rejestru -->

Decyzja Artura z 24.11.2026 (przegląd skrzynek Finansów i back office'u 23–24.11): powiadomienia
portalu Nordei CPro (`noreply@onevms.se`) idą regułą przekierowania ze skrzynek DL/TCM Nordei
na wsparcie@ (regułę zakłada Codex, bez warunku słów), a czytnik spraw je rozpoznaje. Do tej pory
trafiały imiennie do DL-a i PM-a: przedłużenie z 18.11 przeleżało urlop do 23.11, a zmiana nabywcy
z 15.09.2026 (Abp S.A. → Abp Finland) nie dotarła do Finansów. W 2025 ta sama pomyłka skończyła
się korektami za dwa miesiące i refakturą.

## Pięć wzorców (`services/admin_cases/nordea_cpro.py`)

| Wzorzec | Skąd data | Co robi czytnik |
|---|---|---|
| „Contract terminated: <CoA>” | „New end date” z tabeli | propozycja „Klient kończy” |
| „Contract <CoA> will not be extended” (też notatka „won't be prolonged”) | „End day” dopisany przez DL-a; bez niego koniec obecnego zamówienia | propozycja „Klient kończy” |
| internalizacja („Consultant employed at Nordea”, „internalized”) | „New end date” | propozycja „Klient kończy” z dopiskiem o porozumieniu ze zdjęciem zakazu konkurencji |
| przedłużenie („You have N contract extensions to handle”, „prolongation status”) | — | sprawa „Nordea CPro: przedłużenie do decyzji”, etykieta Przedłużenia |
| „Important changes made to contract <CoA>” | data maila („od dnia”), chyba że mail ma „valid from” | zmiana danych do faktury → sprawa Rozliczeń dla Finansów; sama nowa data końca → propozycja „Klient kończy” |

- Numer CoA = tytuł linii zamówienia Nordei (`notice_mail.orders_by_cpro`). Pomiar 24.11 na kopii
  produkcji: 6 z 9 numerów CoA z maili 2026 w archiwum administracja@ trafia w linię zamówienia.
- Archiwum administracja@ (127 maili CPro, 2023–2026): rozpoznane 83, w tym 25 nieprzedłużeń
  (19 bez daty), 24 zakończenia, 6 internalizacji, 24 zmiany (line manager, cost center),
  4 przedłużenia. Reszta to notatki CoA własnymi słowami (stawka, zastępstwo) — zostają zwykłą sprawą.
- **Maile rekrutacyjne CPro nie zakładają spraw** (`mail_ingest._is_cpro_recruitment`, wynik
  `cpro_recruitment`): zamknięcie, odrzucenie i rozmowy prowadzi pętla `cpro_mail` ze skrzynek DL-i
  (`integracje/cpro-maile-nordei.md`). Reguła przekierowuje wszystko z `onevms.se`, a takich maili
  było 334 w trzy tygodnie u dwóch DL-i.

## Zasady, których nie cofamy przy okazji

- **Koniec z CPro otwiera sprawę wyjścia dopiero po „Potwierdź”** (`notice_view._open_exit_case`).
  Jak przy wypowiedzeniu: automat proponuje, człowiek potwierdza. Data = koniec linii zamówienia
  wybrany na karcie („Ustaw koniec…” albo „Zostaw …”), bez niego data z maila. Bez żadnej daty
  sprawa wyjścia nie powstaje, a komentarz w sprawie to mówi.
- **Umowa konsultanta zostaje bez zmian.** Klient kończy zamówienie, nie umowę B2B: porozumienie
  albo przepięcie to kroki sprawy wyjścia (decyzja, rozwiązanie umowy). Przy internalizacji opis
  sprawy przypomina o zdjęciu zakazu konkurencji i opłacie z umowy ramowej (niepotwierdzone, czy ją
  fakturujemy).
- **Sprawa wyjścia z CPro nie znika przy pętli „przedłużono”** (`steps.close_extended_exit_cases`):
  umowa B2B nie ma daty końca, więc bez wyjątku zamknęłaby się w pięć minut. Wyjątek trzyma ją,
  dopóki `contracts.client_order_end_date` nie sięga dalej niż potwierdzony koniec
  (`notice_mail_proposals.decision.exit_last_day`). Przedłużone zamówienie zamyka ją jak dotąd.
- **Zmiana danych do faktury nie zmienia nabywcy ani faktur.** Sprawa z maila dostaje tytuł
  „Nordea CPro: zmiana nabywcy od DD.MM.RRRR · CoA N” (adres faktury, P1) albo „… dane do faktury …”
  (line manager, cost center, NIIDS, P2), obszar Rozliczenia, etykietę Finanse → Zmiany w zamówieniach
  (`triage.cpro_route`), opis „stare → nowe” i checklistę dla Finansów. Kontraktu nie przypina —
  podaje go w opisie z numeru CPro. Zapis nabywcy od miesiąca (`contract_buyers`) robi pętla
  `cpro_mail` (sesja „Zmiany nabywcy kontraktu Nordei z maili CPro”, 24.11.2026), nie czytnik spraw.

## Kroki wyjścia (`services/back_office/steps.py`)

- **Benefity** (nowy krok, `rules.benefits_item`): rezygnację zgłasza się do 19. dnia miesiąca, działa
  od 1. dnia następnego, a benefit trwający po końcu współpracy potrąca się z ostatniego przelewu.
  Pozycja checklisty liczy termin od ostatniego dnia; gdy już minął, podaje najbliższy 19. i miesiące
  do potrącenia. Od 01.01.2027 PZU znika, zostaje karta sportowa. NEXUS nie ma ewidencji benefitów,
  więc pozycja mówi „sprawdź, czy ma”. Sprawa wyjścia sprzed 24.11 nie ma tej pozycji, więc krok zalicza się sam
  (inaczej żadna stara sprawa nie zamknęłaby się po komplecie kroków).
- **Sprzęt do zwrotu** (krok „Zwrot sprzętu i dostępy”): egzemplarze z rejestru `/equipment` wydane na
  kontrakt i niezwrócone. Rejestr obejmuje kontraktorów B2B — posiadaczem bywa kontrakt
  (`ludzie/sprzet-i-protokoly-recepcji.md`; 19.11.2026 27 żywych kontraktów miało taki sprzęt).
  Pozycja „Zwrot sprzętu i protokół” z pakietu klienta („sprzęt od nas”) zostaje obok.

## Start

Działa, gdy czytnik spraw czyta wsparcie@ (`ADMIN_CASES_MAIL_INGEST_ENABLED`) i reguła przekierowania
jest na skrzynkach DL/TCM. Sprawa wyjścia wymaga modułu „cases”. Po pierwszym dniu sprawdź w stanie
czytnika licznik `cpro_recruitment` i czy na tablicy nie ma spraw z tematów „was closed”/„Rejected:”.

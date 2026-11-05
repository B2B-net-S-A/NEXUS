# Portal konsultanta — link z maila, sesja poza JWT, panel po ręcznej aktywacji, jedna karta z dwóch kanałów
<!-- indeks: panel konsultanta, cp_activations, aktywacja po podpisaniu umowy, stan pilot bez modułu back_office, materiały na start, pakiet klienta, mail powitalny, sprzęt z protokołem, szablon rozliczenia klienta, zostań trenerem, stawka w panelu -->

Decyzje Artura z 02.11 i 04–05.11.2026. Konsultant nie ma konta w NEXUSIE: wchodzi linkiem
z maila na `/konsultant`. Kod: `app/api/consultant_portal.py` (publiczne),
`app/api/consultant_panel.py` (aktywacja, materiały, szablon, przełączniki),
`app/api/consultant_portal_staff.py` (back office), `app/services/consultant_portal/`.
Plan: https://claude.ai/artifact/3ahiPR1wWt1PPANeRyb4Wi. Wersja 1 służy testom na pojedynczych
osobach; zlecenia, faktury z KSeF, raporty klientów i subdomena to wersja 2.

## Panel powstaje ręcznie

Automatu nie ma (decyzja Artura 05.11.2026). Po podpisaniu umowy Opieka klika w zakładce „Wejście”
kontraktu: potwierdza adres (trafia do `contracts.candidate_email`), wybiera materiały i wysyła mail.
`open_for` wymaga aktywnego wiersza `cp_activations` w każdym stanie wyłącznika, więc kontrakt bez
aktywacji wygląda z zewnątrz jak nieznany adres. Wyłączenie zostawia wiersz i zamyka sesje od razu.
Adres innej osoby z aktywnym panelem to odmowa. Adres zmieniony w kontrakcie po aktywacji zamyka panel do
ponownego potwierdzenia (`portal_settings.load` porównuje go z `cp_activations.email`), bo inaczej link wyszedłby
na niepotwierdzony adres. Mail powitalny wysyła przy aktywacji Opieka, także bez roli opiekuna kontraktu (decyzja
Artura 05.11.2026); dawna trasa DL/TCM zostaje. Szkic kontraktu nie aktywuje się, bo to umowa przed podpisem.

## Wyłącznik

`app_settings['consultant_portal']` = `{"state": "off"|"pilot"|"all"}`, zmienia admin przez
`PUT /api/consultant-panel/settings` (przełącznik jest w karcie panelu na kontrakcie). Brak wiersza = `off`:
każda publiczna trasa odpowiada 404, także przy poprawnej sesji, a pętle nic nie robią. Każdy mail do
konsultanta idzie przez `portal_mail.send`, który sprawdza wyłącznik dla kontraktu, bo to wysyłka do ludzi
spoza firmy. `pilot` działa bez modułu `back_office`, żeby sprawdzić panel na jednej osobie przed startem
tablicy; dokumenty nie mają wtedy kart u Finansów, a sprawy idą na dzisiejszy kanban Opieki. `all` bez
modułu działa jak `off`. Stan `off` kasuje sesje, więc ponowne włączenie ich nie ożywia. Pakiet klienta
i mail powitalny stoją za modułem „Wejście i odejście”, który ma zostać wyłączony, dlatego ich bramka
przepuszcza też przy włączonym panelu.

## Reguły bezpieczeństwa, które łatwo cofnąć

- Token linku i sesji tylko jako SHA-256 w bazie. Token z maila idzie we fragmencie adresu
  (`/konsultant/wejscie#…`, `/konsultant/ocena#…`), a do API w ciele żądania, nigdy w ścieżce:
  ścieżka trafia do logów. Sesję zakłada POST, bo skanery poczty otwierają adresy same.
- Sesja jest w nagłówku `X-Portal-Session`, nie w `Authorization` i nie jest JWT. Pracowniczy token
  nie działa w portalu, a portalowy nie działa w `/api/**` pracownika. Sesja pada, gdy kontrakt przestaje
  działać, zmienia adres albo traci aktywację.
- Prośba o link odpowiada tym samym zdaniem dla każdego adresu, a mail idzie w tle. Liczy się wyłącznie
  `contracts.candidate_email`; adres dwóch różnych osób nie otwiera niczego.
- „Twoje sprawy” to lista dozwolona (`content.visible_cases_clause`): zgłoszenia z portalu z kluczem
  `portal:` i maile, które konsultant sam napisał. Nigdy obszar `negotiation`, sprawy automatyczne, opis,
  komentarze ani checklista. Wolny tekst „Czeka na” z karty zostaje wewnętrzny: konsultant dostaje stałą
  etykietę „Czekamy na odpowiedź” (decyzja Artura 03.11.2026).
- Moduł publiczny ma `@limiter.limit`, więc nie ma `from __future__ import annotations`.

## Bez kodu SMS

Link z maila jest jedynym krokiem logowania (decyzja Artura 04.11.2026, odwołuje kod SMS z 02.11, do
pokazania IOD). Stawka i faktury są więc za samym linkiem, dlatego adres potwierdza człowiek przy aktywacji,
a danych do przelewu nie da się zmienić w panelu. Tabela `cp_sms_codes` zostaje, bez DROP-a.

## Co wolno pokazać konsultantowi

Odpowiedzi to listy dozwolonych pól (`services/consultant_portal/panel.py`), pilnują ich testy
`test_consultant_panel_screens.py`:

- **Stawka**: tylko stawka konsultanta z `effective_candidate_rate`, bez stawki klienta i marży.
- **Sprzęt**: wyłącznie wydania z protokołem (decyzja Artura 05.11.2026), na ekranie bez cennika, uwag i lokalizacji.
  PDF protokołu ma wartości, tak samo jak dokument z publicznego linku odbioru.
  Stare wydania z importu nie mają protokołu, więc pozycja menu jest ukryta. Potwierdzenie odbioru
  (`protocols.sign_in_panel`) gasi linki do tego protokołu, a zatwierdza dalej recepcja (D4).
- **Materiały**: tylko te wybrane przy aktywacji. Wycofany materiał znika z panelu, wiersz i plik zostają.
- **Szablon rozliczenia** (`client_settlement_rules`) ustawiają Finanse; tabela-siostra, bo `client_playbooks`
  ma bramkę Delivery. `documents.month_row(mode=…)`: przy `client_report` konsultant nie wysyła raportu.
- **Trener**: dane w `cp_trainer_applications`, a obsługa to sprawa `portal:trainer:*`; drugie wysłanie
  poprawia pierwsze zamiast dublować sprawę.

## Rozmowy

Konsultant wybiera osobę z zespołów `care`, `finance`, `contracts` i termin. Organizatorem jest
`CONSULTANT_PORTAL_MAILBOX` przez rejestrację „NEXUS Teams Prep”, więc konto musi być w grupie
`NEXUS-Meetings-Scope`. Termin rezerwuje wiersz `pending` zatwierdzony przed Graphem (częściowy unikat na osobę
i początek). Kalendarz nieczytelny = brak terminów. Własna tabela `cp_meetings`, bo `prep_meetings` wymaga
kandydata i rekrutacji. Transkrypt bez wideo zależy od polityki Teams, której w kodzie nie widać.
Podsumowanie AI (`portal_meeting_summary`) to komentarz w sprawie: awaria modelu niczego nie blokuje. Widzi je
zespół obsługi spraw, a pełny zapis tylko prowadzący, kierownik i osoba prowadząca sprawę; tak mówi zaproszenie
(`INVITE_NOTE`, decyzja Artura 03.11.2026, do pokazania IOD).
Każdy odczyt pełnego zapisu zostawia ślad `portal_transcript_read`. Transkrypt znika po 365 dniach (`TRANSCRIPT_RETENTION`, termin do potwierdzenia z IOD).

## Oceny

Osoba oceniana nie widzi pojedynczych ocen, także kierownik przy własnej rozmowie. Macierz uprawnień tego nie
pokaże, bo reguła siedzi w treści odpowiedzi, dlatego pilnują jej testy `test_consultant_portal_flows.py`.
Ocena 1–2 zakłada zadanie w wierszu oceny (`followup_*`), a nie sprawę, bo sprawy widzi cały zespół.
Przegląd miesięczny pokazuje zbiorcze liczby od 3 ocen.

## Rozliczenia

Portal i czytnik `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` kończą w `documents.store`. Karta to
(kontrakt, okres, rodzaj), kolumna `invoice` zespołu `finance` (`sources.document_cards`). Ten sam plik z drugiego
kanału to ten sam wiersz. Raport przyjęty przez Finanse daje sygnał „wystaw fakturę”. W pilotażu czytnik bierze
tylko nadawców z aktywowanych kontraktów, a nieznany nadawca dostaje kartę do przypisania dopiero w stanie `all`.

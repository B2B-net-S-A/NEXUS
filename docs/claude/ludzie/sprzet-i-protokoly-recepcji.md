# Sprzęt i protokoły recepcji (D2–D10, 16.10.2026)

Ewidencja sprzętu, kart SIM i kart dostępu oraz protokoły zdawczo-odbiorcze
przeszły z Exceli i Worda recepcji do NEXUSA (D1 = tylko NEXUS, uprawnienie
„Sprzęt” osobno od Kadr). Ekran `/equipment`, zakładka „Sprzęt” przy kontrakcie,
osobie z kartoteki i uczestniku Akademii.

## Czego nie przechowujemy (D10)

- Rejestr nie ma kolumn na klucz BitLocker, PUK, PIN, PESEL ani prywatny e-mail.
  Import plików recepcji odrzuca je dwa razy: po nagłówku kolumny (kolumna nie
  jest czytana) i po wzorcu wartości w czytanych kolumnach
  (`app/services/equipment/sanitize.py`). Nowa kolumna w imporcie albo w formularzu
  egzemplarza = sprawdź, czy nie otwiera drogi dla tych danych. Audyt 19.10.2026:
  wzorce łapią też „PIN1 1234”, „PIN karty 1234”, „PUK 1234 5678”, „PUK: 1234-5678”
  i klucz BitLocker z przerwą do trzech znaków między grupami („ - ”, półpauza,
  kropka, nowa linia); uwaga o osobie spoza NEXUSA przechodzi przez tę samą
  kontrolę co notatka egzemplarza (`registry.clean_notes`). Na produkcji
  (497 pozycji) zero trafień w notatkach, lokalizacjach i uwagach (odczyt 19.10).
- Plik importu nie jest przechowywany — partia ma jego SHA-256 i oczyszczone wiersze.
- Artur 18.10.2026 potwierdził: klucze BitLocker zostają w Intune/Entra, PIN i PUK
  u operatora. NEXUS ich nie przechowuje, tylko pokazuje drogę do nich
  (`secretHint` w `equipment-format.ts`, okno szczegółu laptopa, telefonu i karty SIM).

## Rejestr i posiadacze

- Jedna pozycja = jeden fizyczny egzemplarz. Numery ewidencyjny, S/N, IMEI, ICCID,
  numer telefonu SIM i numer karty dostępu unikalne, gdy niepuste.
- „Wolny” = stan `na_stanie` i brak aktywnego wydania. Najwyżej jedno aktywne
  wydanie na egzemplarz pilnuje indeks częściowy (także wyścig dwóch wydań).
- Posiadacz to dokładnie jeden z czterech: konto NEXUSA, kontrakt, osoba
  zewnętrzna bez konta, uczestnik edycji Akademii (`academy_application_id`, 0465).
  CHECK `num_nonnulls(…) = 1` w bazie.
- Cennik per model (D5); wartość pozycji pochodzi z cennika, zmiana przy wydaniu
  dotyczy tylko tego protokołu. Karta SIM i karta dostępu są w protokole bez
  wartości (D6). Własność (`nasz` / `klienta`) przechodzi do zakładki kontraktu.
- **Nowa osoba bez konta** (decyzja Artura 28.10.2026, wariant B): „Wydaj
  sprzęt” krok 1 szuka tylko aktywnych kont, kontraktów od szkicu do
  zakończenia (`ISSUABLE_CONTRACT_STATUSES`) i osób spoza NEXUSA — kandydatki
  bez konta, kontraktu i szkicu wejścia tam nie ma (moduł „Wejście” na
  produkcji wyłączony i ma tak zostać). Pusty wynik mówi, gdzie szukał, i kieruje
  do „Osoba spoza NEXUSA”. Gdy konto powstanie, recepcja klika w menu ⋯ wiersza
  wydanego egzemplarza „Przepisz na konto…” (`POST /external-people/{id}/move-to-user`,
  uprawnienie „Sprzęt”). W jednej transakcji przechodzą na konto: aktywne
  wydania, otwarte zadania i protokoły `oczekuje`/`podpisany`. Protokół
  potwierdzony zostaje przy osobie spoza z migawką (`holder_name`) i dostaje
  wpis w `hr_audit_events` (`equipment_holder_moved_to_user`); zwrócone wydania
  zostają historią osoby spoza. Konto nieaktywne i osoba bez niezwróconych
  rzeczy = 409.
- Twarde skasowanie kontraktu kasuje kaskadą jego wydania — wyzwalacz zwraca
  egzemplarz na stan. Zakładka „Sprzęt” kontraktu (`contract_equipment`) wskazuje
  egzemplarz z rejestru (`item_id`, `assignment_id`).

## Wydanie, zwrot, protokół

- Wydanie i zwrot to jedna transakcja: egzemplarze `FOR UPDATE`, statusy,
  wydania, protokół i — dla konsultanta — pozycje zakładki kontraktu powstają
  razem albo wcale. Stan przy zwrocie decyduje o stanie egzemplarza
  (uszkodzony → serwis, zgubiony → zgubiony).
- Protokół z wzoru recepcji 1:1 (`protocol_template.py`, tabela pozycji, kwota
  słownie `pln_words_with_fraction`), numer `PZO/<rok>/<miesiąc>/<kolejny w roku>`
  pod blokadą doradczą, migawka posiadacza i pozycji zamrożona w chwili wydania.
- Podpis (D4): link dla osoby, papier albo profil zaufany (skan wgrywa recepcja).
  Stan „podpisany” potwierdza CZŁOWIEK — automatyczna weryfikacja podpisu
  zaufanego bywa „nieokreślona”.
- Link (D8): publiczna strona `/protocol/<token>`, trasa
  `/api/public/equipment-protocols/{token}` z limiterem (moduł bez
  `from __future__ import annotations`). Token tylko w adresie, w bazie SHA-256;
  14 dni, jednorazowy; nowy link unieważnia poprzednie. Zły, zużyty, wygasły
  i unieważniony token wyglądają z zewnątrz tak samo.

## Zadania recepcji („Do zrobienia”)

- Zakłada je NEXUS: start kontraktu u klienta, który bierze sprzęt od nas
  (`clients.equipment_provider = 'nasz'`, 7 dni roboczych wcześniej, D7), koniec
  współpracy, wejście i odejście pracownika, niepodpisany protokół, podpisana
  umowa i rezygnacja uczestnika Akademii. `source_key` unikalny — drugie wołanie
  nie dubluje, otwarte zadanie dostaje tylko nowy termin.
- Haki kontraktu (`app/services/hr/contract_hooks.py`) biegną w savepoincie:
  awaria sprzętu nie blokuje zmiany kontraktu. Źródłem prawdy jest przegląd
  `reconcile_upcoming` w pętli HR (kontrakt zmienia stan wieloma ścieżkami).
- Przypomnienie (`equipment_task`, raz dziennie, gdy są zadania po terminie albo
  na dziś i najbliższe dni) i podpis protokołu linkiem (`equipment_protocol_signed`)
  to dymek i mail „Czas i ludzie” (liczba zadań albo numer protokołu i nazwisko
  odbierającego — bez listy sprzętu i bez kwot). Listą zadań jest zakładka „Do zrobienia”, nie powiadomienia.

## Import plików recepcji

- Wgranie → partia z decyzjami (`przyjmij`, `pomin`, `konflikt`, `do_wyjasnienia`)
  → arkusz kontrolny XLSX dla recepcji → poprawki → zatwierdzenie. Nic nie trafia
  do rejestru przed zatwierdzeniem. Laptopów bez stanu nie zgadujemy — idą do
  „Do wyjaśnienia”.
- Arkusz z „aktualn” w nazwie (np. „Aktualne” w pliku kart) wygrywa z kopiami listy
  w innych arkuszach: kopia dostaje „pomiń” z powodem, nie „konflikt”. Duplikat między
  arkuszami bez aktualnej listy zostaje konfliktem. Arkusze ukryte i bez rozpoznanego
  wiersza nagłówków są pomijane i nazwane w raporcie partii (w plikach recepcji:
  „Akcesoria” liczone w sztukach, „Utylizacja…”, notatki o zwrotach, „InTune”).
- Stan z kolumny stanu wygrywa z tekstem w kolumnie osoby: „Status laptopa:
  wolny / czysty / do czyszczenia / gotowy” = na stanie, nawet gdy w
  „Użytkownik” stoi „Gotowy” albo „Stoi na Open” (ten tekst idzie do uwag).
  „do wyjaśnienia” w pliku zostaje „do wyjaśnienia”. Słowa stanu w kolumnie
  osoby (utylizacja, wykupiony, zablokowana → wycofany; uszkodzony → serwis;
  zaginiona → zgubiony) też są stanem. Wiersze „RAZEM / ZAPAS / BIURO UŻYWA”
  są pomijane. Kopia z listy „Wolne …” = „pomiń”, nie konflikt.
- Osoba z kolumny osoby: 2–3 słowa z wielkiej litery po zdjęciu dopisków
  („recepcja”, „obecnie posiada”, „(zamiana)”, „?”); w łańcuchu „A -> B”
  posiadaczem jest ostatni. Szukamy po kolei: aktywne konto, kontrakt w toku,
  konto nieaktywne, kontrakt zakończony — parami: ta sama nazwa na aktywnym
  koncie i na kontrakcie w toku (albo na nieaktywnym i zakończonym) oraz
  imiennicy w jednej warstwie = „do wyjaśnienia” („kilka osób o tym imieniu
  i nazwisku”), bo sprzęt konsultanta na koncie gubi zadanie „Odbierz sprzęt”
  przy końcu kontraktu (audyt 19.10.2026). Nie ma nikogo = „przyjmij” na **osobę
  spoza NEXUSA** (jedna na nazwisko, notatka „z importu plików recepcji”);
  wybór konta albo kontraktu w partii zastępuje tę propozycję. Tekst, który nie
  jest osobą („Igor do wysyłki maili”, „Karta dla ochrony”), zostaje „do wyjaśnienia”.
- Imię z kolumny bez nagłówka tuż przed „Użytkownik” (zestawienie SIM ma
  w „Użytkownik” samo nazwisko) jest doklejane do nazwiska.
- Ponowne wgranie pliku o tej samej nazwie zastępuje jego niezatwierdzoną
  partię (wiersze → „pomiń”, `summary.superseded`), żeby licznik „do
  wyjaśnienia” nie liczył porzuconych partii. Partia z zapisanym wierszem
  nie jest zastępowana.

## Intune (etap 4, D9) i edycje Akademii (etap 5)

- Intune: wyłącznie odczyt (`DeviceManagementManagedDevices.Read.All`, zgoda
  administratora przy przełączeniu), migawka w `equipment_intune_devices`,
  rozjazdy z ewidencją liczone przy odczycie, recepcja je wyjaśnia albo pomija.
  Bez kluczy odzyskiwania i danych spoza urządzenia.
- Edycja Akademii = program i miesiąc startu (`cohort_month`), NIE termin spotkania
  (`academy_sessions` to terminy w biurze): check lista recepcji per edycja
  (`academy_edition_checklist`), uczestnicy przed podpisem liczeni do najbliższej edycji,
  hotel i bilet uczestnika (`academy_participant_logistics`), zestaw i protokół
  z wydań sprzętu. Rezygnacja zamienia „zrobione” hotel i bilet na
  „do anulowania” i zakłada zwrot, jeśli uczestnik ma rzeczy.

## Wzory protokołów i pakiet klienta (etap 3, O3, 17.10.2026)

- **Wzory wgrywa recepcja** („Sprzęt → Wzory protokołów”, uprawnienie
  „Sprzęt”, admin): plik Word z polami `{{ … }}` — te same pola co standard
  (`protocol_template.FIELDS`, wiersz tabeli `line.*`). Punkt wyjścia:
  „Standard wydania / zwrotu” do pobrania. Wymagane pola rodzaju:
  `number`, `protocol_date`, `holder_name`, `lines`; pole spoza listy = 422.
- **Plik od człowieka wypełnia się wyłącznie w sandboxie** jinja2
  (`protocol_template.sandboxed_env`, docxtpl `render(…, jinja_env=…)`): bez
  atrybutów Pythona, makr, dołączania plików i funkcji globalnych, krótka
  lista filtrów, bez potęgowania, mnożenia i formatowania napisów. Przy
  wgraniu: tylko `.docx` (zip bez makr), 2 MB spakowany / 40 MB rozpakowany,
  próbne wypełnienie fikcyjnym protokołem. Wbudowany standard (kod NEXUSA)
  zostaje na zwykłym `Environment` — nowy wzór z pliku NIGDY.
- **Wzoru się nie podmienia ani nie kasuje**: treść pliku leży w bazie
  (`equipment_protocol_templates.content`), nowy plik = nowy wzór, stary się
  wycofuje. Wycofanie wzoru wybranego w pakiecie klienta = 409. Protokół
  pamięta wzór (`equipment_protocols.template_id`, `template_version =
  wzor-<id>`) i zawsze pobiera się z niego (`protocols.render_docx` /
  `render_pdf`), także po wycofaniu.
- **Wzór dla klienta wybiera się w pakiecie** („Klienci → Wejście u klienta”,
  osobno wydanie i zwrot). Protokół kontraktu bierze wzór z pakietu klienta
  kontraktu w chwili sporządzenia; wycofany albo brak = standard. Konto,
  osoba spoza NEXUSA i uczestnik Akademii — zawsze standard.

## Ekrany po makiecie 19.10.2026 (Ewidencja, Do zrobienia, Wydaj sprzęt)

Makieta z kanwy przeglądu „Ludzie i Sprzęt” (decyzja Artura 19.10.2026:
wdrożyć razem z drobnymi dodatkami; liczby w makiecie były przykładowe,
logika modułu bez zmian).

- **Ewidencja.** Kafle stanu nad zakładkami (tylko na „Sprzęt”): wolne per
  kategoria z paskiem wydane / wolne / serwis — klik = filtr kategorii, drugi
  klik zdejmuje; „Czeka na podpis” (najstarszy protokół w dniach) i „Z importu”
  prowadzą do zakładek. Liczby z `GET /summary` (`by_category`,
  `oldest_waiting_on`, `unsigned_items`). Chipy stanu liczą cały rejestr, nie
  bieżący filtr; „Bez podpisu” = `GET /items?unsigned=true` (wydane, protokół
  wydania `oczekuje` albo `podpisany`). Widok „Modele” (`?view=modele`): wydane
  i serwis sztukami, na stanie zwinięte po modelu; „Wydaj” bierze pierwszą wolną
  sztukę po numerze ewidencyjnym (porównanie liczbowe: 095 < 148), numer zmienia
  się w oknie wydania. Grupa modelu = kategoria + nazwa bez wielkości liter
  i nadmiarowych spacji (`modelKey`): import Exceli założył ten sam model kilka
  razy („Laptop DELL Vostro 3530” i „Laptop Dell Vostro 3530”, prod 20.10), etykieta
  z najczęstszego zapisu, cena z modelu wybranej sztuki. To samo w „Wydaj sprzęt”
  krok 2. Sekcje „Wydane” i „Wycofane i zgubione” pokazują 5 wierszy
  i „Pokaż wszystkie”. Ekran czyta do 500 pozycji naraz (`limit`), więcej =
  podpowiedź „zawęź filtrem”. Rzadkie zakładki (Wzory, Cennik, Intune,
  Akademia) są pod „Więcej”; aktywna rzadka zakładka pokazuje się w pasku.
- **Akcje wiersza.** Protokół `oczekuje` → „Wyślij link” (pyta: nowy link
  unieważnia poprzedni, D8), `podpisany` → „Potwierdź” (pyta: podpis potwierdza
  człowiek, D4), wydany i potwierdzony → „Zwrot”, wolny → „Wydaj”, serwis →
  „Wróciło” (stan `na_stanie`). Reszta w menu ⋯.
- **Do zrobienia.** Agenda wg terminu: Po terminie → Dziś → Później (bez
  terminu na końcu), chipy rodzaju, jedna główna akcja na zadanie, „Zrobione”
  i „Nie dotyczy” w ⋯. Zadanie podpisu niesie stan i skład protokołu
  (`protocol.status`, `protocol.categories`): podpisany = „Potwierdź”, inaczej
  „Wyślij link ponownie”. Tytuł zadania podpisu = „Podpis protokołu: <osoba>”;
  numer protokołu · klient · „wysłany DD.MM” (`protocol.client_name`,
  `protocol.link_sent_on` = dzień ostatniego linku) idą do drugiej linii, bo przy
  1280 z paskiem bocznym numer ucinał nazwisko (20.10). Starsze zadania mają
  numer w zapisanym tytule — front składa tytuł sam (`taskTitle`). Ikony składu
  schodzą pod tekst, gdy w wierszu brak miejsca. „Ten tydzień w recepcji” = otwarte zadania pon–pt,
  zaległe liczone do dziś; w weekend nadchodzący tydzień.
- **„Przypomnij” o zwrocie** (`POST /tasks/{id}/remind`, uprawnienie „Sprzęt”):
  tylko otwarte zadanie `zwrot` (inne = 409). Konto NEXUSA dostaje dzwonek
  i mail „Czas i ludzie” `equipment_return_reminder` (0479) z prośbą i terminem
  — bez listy sprzętu i kwot, link do „Mój czas → Kartoteka”. Konsultant, osoba
  spoza NEXUSA i uczestnik Akademii nie mają konta: trasa oddaje adres, recepcja
  wysyła wiadomość ze swojej poczty (jak link do podpisu); brak adresu = 409.
  Konto wyłączone (odejście) = 409 „przypomnij telefonicznie”, bez wpisu
  „przypomniano”; dzwonek, który nie wyszedł (wyciszone „Czas i ludzie” albo
  przypomnienie już dziś), daje kanał `mail` z adresem konta (audyt 22.10.2026).
  Każde przypomnienie zostaje w `details` zadania (`reminded_on`, `reminders`),
  wiersz pokazuje „przypomniano dd.mm”. Na wierzchu tylko przy zwrocie po
  terminie, w terminie — w ⋯.
- **Gotowe zestawy** są w kodzie (`ISSUE_KITS` w `equipment-format.ts`), bo
  NEXUS nie ma wzoru zestawu: pakiet klienta wybiera tylko wzór protokołu,
  a zestaw edycji Akademii recepcja składa z modeli przy wydaniu. Kontraktor =
  laptop, telefon, SIM, słuchawki, karta dostępu; biuro = laptop, monitor,
  słuchawki, karta dostępu. Słuchawki to akcesorium po nazwie modelu
  („słuchawk”/„headset”). „Dodaj zestaw” bierze pierwszą wolną sztukę na każde
  miejsce, pomija miejsca zajęte już pozycją szkicu i mówi, czego zabrakło.
  Zadanie z powodem `start_kontraktu` podpowiada zestaw kontraktora, `wejscie`
  — biura. Zmiana składu = zmiana listy i tej reguły.
- **„Czy starczy na wydania?”** liczy front (`stockCoverage`): miejsca
  zestawów z otwartych zadań „Przygotuj” per kategoria kontra
  `free_by_category`. Słuchawki liczą się jako akcesoria (licznik stanu nie
  rozróżnia akcesoriów po nazwie). Zakup i zadanie bez powodu — bez zestawu.

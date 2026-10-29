# Urlopy i M365, „Mój miesiąc”, płace, wejście i odejście (16.10.2026)

## Urlopy (`app/services/hr/leave_*.py`)

- Reguły liczą czyste funkcje `leave_policy.py`; zapis, powiadomienia i kolejka
  M365 — `leave_service.py`. Każda decyzja to warunkowy `UPDATE … WHERE status`:
  drugi akceptujący dostaje 409, nie drugą decyzję.
- Dzień urlopu to wiersz `leave_request_days` z `UNIQUE (user_id, day) WHERE active`
  — baza nie pozwala na dwa nakładające się wnioski.
- Pula liczona per rok kalendarzowy DNIA (urlop 29.12–02.01 zjada pulę dwóch lat);
  B2B zużywa pulę dniami płatnymi; urlop na żądanie 4 dni i opieka nad dzieckiem
  2 dni w roku; dzień jest niepodzielny, pół dnia mieści się w połówce puli.
- **Nikt nie decyduje o własnym wniosku, także admin** (reguła + CHECK
  `decided_by <> user_id`).
- Zgodę na przekierowanie poczty do zastępcy daje tylko osoba składająca wniosek.
  Przekierowanie tylko do zastępcy z adresem w domenie z `SSO_ALLOWED_DOMAINS`:
  422 przy wniosku albo zgodzie, wykonawca M365 odmawia (`substitute_outside_company`).
- Akceptacja urlopu usuwa godziny z dni urlopu w „Moim miesiącu” i przelicza
  sumę kontrolną (`time_hooks.on_leave_approved` / `on_leave_cancelled`).
  Pół dnia nie kasuje godzin, tylko skraca zwykłe ręczne wpisy dnia do 4 h
  (od najpóźniej dodanego, nadgodzin i auto-wpisu `leave_paid` nie rusza;
  ślad `leave_hours_trimmed`) — decyzja Artura z 28.10.2026, bo wpis 8 h
  sprzed wniosku dawał akceptującemu 12 h.
- Powiadomienia (dymek) i mail zastępcy nie zdradzają rodzaju ani notatki (D6);
  mail „Czas i ludzie” nie niesie rodzaju nikomu, także przełożonemu i Kadrom
  (`services/hr/hr_mail.py`, reguła w `modul-ludzie-dostep-schemat-i-przelaczenie.md`).
  Trwałe miejsce spraw do decyzji to „Ludzie → Akceptacje” z licznikiem.

### Forma współpracy: słowa i zgłoszenie zamiast wniosku (etap 2, D1, D4–D9, 17.10.2026)

Prawie cała firma jest na B2B albo zleceniu, umowa o pracę pojedynczo. Od
08.07.2026 PIP sam stwierdza stosunek pracy, a „wniosek urlopowy” akceptowany
przez „przełożonego” to sygnał podporządkowania — dlatego forma z kartoteki
decyduje o słowach i o przebiegu nieobecności.

- **Jeden słownik** (D4): `app/services/hr/employment_terms.py`
  (`EMPLOYMENT_TERMS` + zdania tylko backendu w `BACKEND_TERMS`) i lustro słowo
  w słowo `frontend/src/lib/hr-employment-terms.ts` (strażnik
  `tests/test_hr_employment_terms_mirror.py`). UoP: urlop, wniosek, przełożony,
  ewidencja czasu pracy, lista płac; B2B: przerwa w świadczeniu usług,
  zgłoszenie, koordynator, raport godzin, faktura; zlecenie: nieobecność,
  zgłoszenie, koordynator, potwierdzenie godzin (art. 8b), rachunek. Brak formy
  = jak UoP. Nie pisz „urlop”, „wniosek”, „przełożony” na sztywno w tekstach,
  które widzi osoba na B2B albo zleceniu — bierz słowo ze słownika (ekrany,
  powiadomienia urlopów i raportu godzin, PDF raportu, przypomnienie 1.–5.).
  Rodzaj „vacation” osoby na B2B/zleceniu ma etykietę „Przerwa w świadczeniu
  usług” / „Nieobecność” (`leave_policy.type_label`). Autoodpowiedź M365 i
  wydarzenie w kalendarzu mówią „poza biurem” — słowa „urlop” tam nie ma.
- **Przełożony / koordynator = jedna funkcja** `recipients.supervisor_of`
  (urlop, czas, zadania; 17.10.2026): przełożony z kartoteki z aktywnym kontem
  i statusem innym niż `exited` → head pionu → Kadry (bez adminów). Head pionu
  akceptuje wnioski, timesheety i wpisy za osoby swojego pionu bez żywego
  przełożonego. Etykieta „akceptuje” w podglądzie wniosku i w „Moim miesiącu”
  liczy się tą samą regułą — nie dopisuj drugiej.
- **Kto odszedł, nie ma podwładnych** (17.10.2026): kartoteka `exited` albo
  wyłączone konto = brak zespołu w każdym zakresie („Mój zespół”, akceptacje,
  kolejki, pełna kartoteka — `people.can_supervise` w `direct_report_ids`), a
  jako nowy przełożony taka osoba to 422.
- **Zgłoszenie zamiast wniosku** (D5, Artur 17.10): na B2B i zleceniu własna
  nieobecność jest od razu `approved` bez decydującego (`decided_by` NULL),
  M365 i godziny od razu. Informacja (`hr_absence_reported`, bez rodzaju) idzie
  do koordynatora: przełożony z kartoteki → head pionu
  (`app_settings['hr_divisions']`) → Kadry; zastępca nieobecnego przełożonego
  do wiadomości. Zgłoszenia nie trafiają do kolejki wniosków ani do licznika
  „Akceptacji”; w „Akceptacjach” są w sekcji „do wiadomości”
  (`reported` w `GET /approvals/pending`) z „Zgłoś kolizję”.
- Zgłoszenie na dzień z miesiąca, którego raport godzin jest wysłany albo
  przyjęty = 409 (podgląd: `blocking_reason`), bo wchodzi bez niczyjej decyzji
  — najpierw koordynator cofa raport do szkicu (17.10.2026; UoP bez zmian).
  Kadry (wpis za osobę, edycja, anulowanie) i anulowanie przez osobę mogą
  zmienić godziny wysłanego albo przyjętego raportu B2B/zlecenia, ale
  koordynator dostaje dzwonek „…: godziny zmienione po wysłaniu” bez rodzaju
  (`leave_recipients.report_sent_timesheet_changed`, decyzja Artura 19.10.2026).
- **Wpis za osobę na B2B albo zleceniu — tylko Kadry i admin** (decyzja Artura
  19.10.2026, D5): koordynator dostaje 403 na `/approvals/on-behalf` (także
  podgląd i zastępcy wpisu), a `GET /approvals/people` oznacza takie osoby
  `can_enter: false` (lista służy też filtrowi historii, więc osoba zostaje).
- Podgląd WŁASNEGO wniosku (`department_absent`, `substitute_absent`) liczy
  tylko zatwierdzone nieobecności innych — oczekujące widzi krąg D6 (decyzja
  Artura 19.10.2026); podgląd wpisu za pracownika — także oczekujące.
- Akceptuj/odrzuć zgłoszenie = 409 (`REPORT_NOT_DECIDED`); czekający wniosek
  osoby, której forma zmieniła się z UoP po złożeniu, dalej można rozstrzygnąć.
  Anulowanie zgłoszenia przez koordynatora = 403 (to odrzucenie pod inną
  nazwą) — anuluje sama osoba (przed pierwszym dniem) albo Kadry/admin.
- **Kolizja**: `POST /api/hr/leave/{id}/conflict` (`{note}` 3–1000 znaków,
  bramka akceptujących + head pionu osoby bez przełożonego) → typ
  `hr_leave_conflict` do osoby (link `/my-time?tab=leave`), ślad
  `leave_conflict_reported` z notatką; zgłoszenie zostaje zatwierdzone. Wiersz
  wniosku niesie ostatnią kolizję (`conflict`), osoba widzi ją przy terminie.
  Mail ma zdanie typu, bez notatki (wolny tekst). Kolizja tylko dla
  trwających i przyszłych zgłoszeń B2B/zlecenia (UoP, minione, zamknięte = 409).
- Import z Compassa: oczekujący wniosek osoby na B2B/zleceniu wchodzi jako
  przyjęte zgłoszenie (`decided_at` = data złożenia), raport liczy je w
  `extra.contractor_pending_reported`.
- **Pula** (D6): na zleceniu nie ma puli płatnych dni — `PUT …/entitlements`
  z dniami > 0 dla zlecenia = 422; B2B tylko gdy umowa ją ma. Wiersz puli
  z czasu innej formy (UoP → zlecenie) zostaje jako historia, ale plan dni,
  podgląd, saldo, most do godzin i import liczą zlecenie jak bez puli
  (`leave_policy.pool_applies`). **Staż** (D9):
  `leave_seniority_years` + `zus_certificate_received_on` w kartotece (tylko
  UoP); `suggested_entitlement_days` (20 / 26 od 10 lat) w kartotece i w
  odpowiedzi zapisu puli — tylko podpowiedź, pulę zatwierdzają Kadry.
- **Uczeń/student na zleceniu** (D8): `student_contribution_exempt` +
  `contribution_exempt_until` (CHECK: data tylko przy znaczniku; znacznik tylko
  na zleceniu — serwis, zmiana formy go zdejmuje). Bez daty urodzenia: Kadry
  wpisują wcześniejszą z dat (koniec statusu albo dzień przed 26. urodzinami).
  `student_reminders.student_contribution_reminders` (z pętli `hr_lifecycle`,
  od 8:00) od 30 dni przed datą do niej włącznie: `hr_lifecycle_task` do Płac
  i Kadr, raz na osobę i datę (`hr_job_runs` `hr_student_contribution_reminder`,
  `u<id>:<data>`). Plakietka „składki od MM.RRRR” w Strukturze i „Moim zespole”.

### Zastępca nieobecnego przełożonego (17.10.2026, `leave_substitute.py`)

- Przełożony na **zatwierdzonym** urlopie obejmującym **cały** dzisiejszy dzień
  (kalendarz firmy; pół dnia i wniosek oczekujący się nie liczą) wskazał we
  wniosku zastępcę. Do końca tego urlopu zastępca widzi w „Akceptacjach”
  wnioski podwładnych tego przełożonego, akceptuje i odrzuca je (bez anulowania
  i wpisu za pracownika) i akceptuje ich timesheety. Zakres kończy się sam —
  nie ma nic do sprzątania.
- Zakres to tylko podwładni nieobecnego przełożonego: nie on sam, nie cudzy
  zespół (404 jak u przełożonego cudzego zespołu), nie własny wniosek (403).
- D6: zastępca nie należy do kręgu. Rodzaj widzi tylko przy planowych
  (`SUBSTITUTE_VISIBLE_TYPES`); L4, urlop opiekuńczy, siła wyższa,
  macierzyński i oddanie krwi to dla niego „Nieobecność” do wiadomości (403
  przy decyzji) — taki wniosek dostają też Kadry, żeby nie czekał do powrotu.
  Notatki wniosku zastępca nie widzi nigdy. W timesheecie dni urlopu bez rodzaju.
- Nowy wniosek: powiadomienie do przełożonego i do zastępcy („w zastępstwie
  za …”); L4 — zastępca dostaje „do wiadomości” bez rodzaju.
- Ślad decyzji: `details.as_substitute_for` = „w zastępstwie za …” (+ id).
- Osoba od Cpro wskazuje we wniosku osobnego zastępcę do Cpro
  (`cpro_substitute_user_id`, 29.10.2026) — reguła w
  `rekrutacja-tablica/cpro-zastepca-z-wniosku-urlopowego.md`.
- Plakietka przy osobie poza „Ludźmi” (lista „@”, kolumna „Rekruter” na
  `/jobs`) bierze `GET /api/hr/leave/absence` raz na listę i tylko przy
  otwartym module urlopów; awaria = brak plakietki, nie błąd ekranu. Po
  oznaczeniu nieobecnej osoby z zastępcą pole podpowiada „Oznaczyć też
  zastępcę?”.

## Microsoft 365 (`app/services/hr/m365/*`)

- Własna rejestracja aplikacji HR (D3), RBAC for Applications po stronie Exchange.
  Tryby `HR_M365_MODE`: `off` (operacje czekają w kolejce), `simulate` (te same
  żądania lądują w `hr_m365_operations.simulated_request` — lokalnie i do
  przeglądu w Kadrach → „Microsoft 365”), `live` (tylko skrzynki z
  `HR_M365_MAILBOX_ALLOWLIST`, pusta lista = wszystkie).
- Kolejka `hr_m365_operations` z `dedupe_key`, rezerwacja `FOR UPDATE SKIP LOCKED`,
  odroczenia 5 min → 30 min → 2 h → 6 h, po 6 próbach `failed`. W `last_error`
  kategoria błędu, nigdy treść odpowiedzi Graph. Każda operacja przed zapisem
  w skrzynce czyta wniosek — anulowany urlop nie dostanie autoodpowiedzi.
- Autoodpowiedź „nasza” niesie znacznik NEXUSA albo Compassa
  (`compass-managed-oof-v1`) — po przełączeniu NEXUS przejmuje te z Compassa.
  Własna autoodpowiedź osoby (bez znacznika) jest nietykalna. Okno liczone
  w datach warszawskich.
- Reguła przekierowania: nazwa `NEXUS · zastępstwo · {uuid}` (rozpoznajemy też
  `COMPASS · zastępstwo · {uuid}` — import zachowuje UUID), otwarcie pierwszego
  dnia urlopu, zamknięcie po ostatnim, `forwardTo` (kopia), domeny firmy z
  `SSO_ALLOWED_DOMAINS`. Reguła Outlooka nie ma warunków czasowych — sprzątanie
  sierot w uzgadnianiu 07:00 jest obowiązkowe.
- Wydarzenie w kalendarzu: prywatne „Poza biurem”, bez rodzaju nieobecności.
- **Osoba, która odeszła** (konto wyłączone albo kartoteka `exited`, 19.10.2026):
  jej skrzynka jest poza grupą aplikacji, więc Graph odpowiada 403. Uzgadnianie
  jej nie czyta (licznik `skipped_exited`, nie `read_errors`), a wykonawca kończy
  jej zaległe operacje jako `skipped: user_exited` bez wywołania Graph
  (`executor.left_company`). Właściciel urlopu bez kartoteki z aktywnym kontem
  nadal jest uzgadniany.
- **Uprawnienia rejestracji „NEXUS Kadry”**: APPLICATION `MailboxSettings.ReadWrite`,
  `Calendars.ReadWrite`, `Mail.Send` zawężone RBAC for Applications do skrzynek
  zespołu, plus `User.Read.All` (odczyt profili niżej). `User.Read.All` to
  uprawnienie katalogu Entra ID, nie Exchange — RBAC for Applications go nie
  zawęża; daje stanowiska, działy i telefony całego tenanta, bez poczty.

### Luki z Compassa przed przełączeniem 24.10 (18.10.2026)

- **Autoodpowiedź z Outlooka bez wniosku → wniosek** (`leave_outlook.py`,
  krok 4 uzgadniania o 7:00 i „Uzgodnij teraz”). Własna autoodpowiedź osoby
  z harmonogramem: dni robocze okna (start od 15:00 = następny dzień, koniec do
  9:00 = bez dnia końca — reguły Compassa) bez aktywnego wniosku stają się
  wnioskiem `vacation`, `source='outlook_oof'`, `created_by` NULL, z notatką
  „Wykryte z autoodpowiedzi w Outlooku (od–do)…”. UoP — czeka na przełożonego
  (`hr_leave_requested`); B2B i zlecenie — przyjęte zgłoszenie, informacja do
  koordynatora i Kadr typem `hr_absence_reported` (bez nowego typu). Odcinek
  ponad pulę UoP albo na dni z wysłanego raportu godzin nie powstaje. Wniosek
  `outlook_oof` pokrywa na stałe całe okno autoodpowiedzi, z którego powstał
  (także skrócony edycją, odrzucony albo anulowany), a odrzucony albo
  anulowany wniosek dowolnego źródła — swoje dni (audyt 19.10.2026). Bez
  autoodpowiedzi i wydarzenia od nas (`_enqueue_m365` i uzgadnianie je
  pomijają; przekierowanie za zgodą osoby zostaje). Autoodpowiedź bez dat →
  bez wniosku, `custom_oof_detected` (lista w karcie). Tylko przy włączonym
  module urlopów.
- **Karta Microsoft 365 → przekierowania** (`m365/forward_admin.py`):
  `GET /forwards` (z bazy), `POST /forwards/check` (odczyt reguł na żywo,
  tylko tryb `live`; inny tryb = zdanie, nie błąd), `POST /forwards/close`
  (`forward_rule_close` przez kolejkę; reguły trwającego urlopu ze zgodą tak
  nie zamkniesz — 409, od tego jest wyłączenie we wniosku), `POST /reconcile`
  („Uzgodnij teraz”: bez rezerwacji dnia i bez 7:00; blokada
  `hr_m365_reconcile_lock` wspólna z przebiegiem dziennym — równoległy ręczny
  dostaje 409, dzienny kończy dzień jako `failed` i bierze go kolejny obrót).
  Każde działanie w `hr_audit_events`.
- **Kadry wyłączają przekierowanie cudzego wniosku**
  (`POST /api/hr/leave/approvals/{id}/forward-off`, powód 3–500 znaków
  w śladzie `forward_consent_off`, osoba dostaje powiadomienie bez powodu).
  Włącza z powrotem tylko sama osoba.
- **Edycja wniosku** (`leave_edit.py`, `PATCH /api/hr/leave/approvals/{id}`):
  rodzaj, daty, pół dnia, zastępca — przełożony, head pionu, Kadry, admin
  (zastępca nieobecnego przełożonego nie); zgłoszenie B2B/zlecenia tylko Kadry
  i admin (403 dla koordynatora, D5). Dni i pula jak przy złożeniu
  (`exclude_request_id`), kolizje bez samego wniosku, tekst OOF zostaje,
  zgoda na przekierowanie tylko przy tym samym zastępcy (inny albo brak
  zastępcy ją zdejmuje — osoba dostaje to w powiadomieniu i może ją włączyć
  sama). Wiersz wniosku idzie `FOR UPDATE` i status jest sprawdzany ponownie
  (równoległe anulowanie = 409). Zatwierdzony: godziny (`time_hooks`) i `leave_m365.plan_edit`
  (zdjęcie starej autoodpowiedzi, nowa, przesunięcie wydarzenia tym samym
  `transactionId`, zamknięcie + otwarcie reguły; klucze `…:edit{n}`).
  Wykonawca pomija `set_oof` i `calendar_event_upsert`, których okno nie
  zgadza się już z datami wniosku (`leave_changed`). Wydarzenie bez
  zapamiętanego id szukamy w starym i nowym oknie (`previous_*` w ładunku):
  nasze przesuwamy, wydarzenie Compassa (`leave-{id}`, z rodzajem w tytule)
  kasujemy (audyt 19.10.2026).
- Uzgadnianie nie przywraca autoodpowiedzi urlopu, po której weszła nasza
  autoodpowiedź urlopu zaczynającego się nie wcześniej — wykonawca pisze taką
  tylko do skrzynki bez naszej trwającej, więc osoba wyłączyła tę pierwszą.
  Przekazanie autoodpowiedzi po anulowaniu pomija wnioski z Outlooka.
- **Anulowanie terminu, który już trwa albo minął** (decyzja Artura
  28.10.2026): osoba faktycznie była nieobecna, więc od pierwszego dnia
  (`start_date <= business_today()`) sama nie anuluje ani zatwierdzonego, ani
  OCZEKUJĄCEGO wniosku — `own_cancel_refusal` = 422, `can_cancel: false`,
  warunek `start_date > dziś` także w UPDATE `cancel_own`. Cofa przełożony albo
  Kadry (`POST /approvals/{id}/cancel`) i od pierwszego dnia musi podać powód:
  ciało `{reason}` 3–500 znaków (`approver_cancel_refusal`, brak = 422 po
  polsku; przed pierwszym dniem powód opcjonalny, a bez powodu UPDATE ma
  warunek `start_date > dziś`). Powód idzie do śladu `leave_cancelled`
  (`details.reason`, wrażliwość `health` jak notatka) i tylko do dymka osoby
  („… Powód: …”); przełożony i zastępca dostają dymek bez powodu, a mail
  ucina treść przed „Powód: ” (`hr_mail.mail_text`, D6). Front: „Anuluj”
  w „Wszystkich wnioskach” przy trwającym albo minionym terminie otwiera
  `CancelLeaveDialog` (słowa raportu godzin z formy osoby), przyszły — zwykłe
  `useConfirmV2`.
- **„Wszystkie wnioski”**: `counts` per status w odpowiedzi historii (zakres
  i filtry bez statusu), plakietki źródła „Wpis za pracownika”, „Z Outlooka”,
  „Import z Compassa”.
- **Kalendarz zespołu**: praca zdalna („Z”) i delegacja („D”) z wierszy
  `attendance_days` (bez notatki, tylko przy module czasu otwartym dla
  patrzącego; domyślna praca zdalna z kartoteki się nie pokazuje); filtr
  „Wszyscy / Nieobecni / Zdalnie” — dziś w bieżącym miesiącu, w innym
  ktokolwiek w miesiącu; delegacja liczy się do „Nieobecnych” (jak „OOO”
  w Compassie).

### Załącznik do wniosku (`leave_proofs.py`, 0473, 18.10.2026)

Compass miał przy wniosku plik do 5 MB (`uploadLeaveProof`). W NEXUSIE załącznik jest
dokumentem e-teczki osoby rodzaju „potwierdzenie nieobecności” (`absence_proof`)
z odnośnikiem `hr_documents.leave_request_id`.

- Dołącza tylko sama osoba do własnego wniosku: przy składaniu (okno wysyła plik zaraz
  po zapisie wniosku; gdy plik nie przejdzie, wniosek zostaje, a toast mówi, że plik
  dołącza się z tabeli) albo później z „Moje nieobecności” (`POST /requests/{id}/proofs`).
  Wniosek oczekujący albo zatwierdzony; do odrzuconego i anulowanego — 409. Najwyżej
  5 plików na wniosek, ten sam plik drugi raz — 409 (indeks żywych uploadów osoby).
- PDF, JPG, PNG do 5 MB (DOCX nie — to skan albo zdjęcie dokumentu), typ z treści
  (`documents_store.check`), nazwa od człowieka tylko w bazie. Okno podpowiada dokument
  przy urlopie okolicznościowym, opiece nad dzieckiem i krwiodawstwie; L4 przychodzi
  przez e-ZLA, więc bez wymogu. Zgłoszenia B2B i zlecenia (D5) nie mają pola ani kolumny.
- Kto widzi (D6): liczbę (`proof_count`, „Załącznik ✓”) — osoba, przełożony, Kadry;
  listę z pobraniem (`proofs`) — osoba i Kadry. Kadry pobierają przez
  `GET /approvals/{id}/proofs/{doc}/file` (bramka `require_hr_leave_proof_reader` =
  uprawnienie „Kadry”); przełożony dostaje 403, a e-teczki osoby nie widzi wcale.
  Zastępca nieobecnego przełożonego nie dostaje listy, a przy rodzaju ukrytym (L4
  i pokrewne) nawet liczby — zdradzałaby rodzaj.
- Krąg dokumentu: osoba i Kadry (bez Płac i recepcji); ślad w `hr_audit_events`
  z `sensitivity='health'` — także każde pobranie pliku z wniosku (`document_downloaded`,
  obie trasy `…/proofs/{doc}/file`, audyt 21.10.2026), jak w e-teczce. Od 19.10.2026 pilnuje tego serwer dla każdego potwierdzenia
  nieobecności w e-teczce: wgranie albo zmiana kręgu z Płacami lub recepcją = 422
  „Potwierdzenie nieobecności widzą tylko osoba i Kadry.” (`documents.check_audience`).
  Osoba usuwa plik, który sama dodała (pomyłka) — plik znika, wiersz zostaje jako ślad
  „mistake”; plik dodany przez Kadry usuwają Kadry.
- Import z Compassa przenosi tylko informację, że plik był; stare pliki zostają
  w magazynie Compassa.

### Kartoteka z katalogu M365 (`m365/profile_sync.py`, `m365/directory.py`)

- Raz dziennie od 6:00 (pętla `hr_m365_daily`, rezerwacja `hr_job_runs`
  `hr_m365_profile_sync` per dzień), tylko przy włączonym module `people`.
  `GET /users/{upn}?$select=jobTitle,department,mobilePhone,businessPhones,accountEnabled`
  dla kartotek `onboarding/active/offboarding` z aktywnym kontem.
- Przepisujemy tylko pola, które kartoteka ma: `job_title`, `department`, `phone`
  (komórka, a bez niej pierwszy numer biurowy — kolejność Compassa, inaczej
  pierwsza synchronizacja przestawiłaby telefony). `officeLocation` nie
  przenosimy: kartoteka ma tylko biuro/zdalnie, a to ustalają Kadry.
  `accountEnabled = false` przy aktywnej kartotece tylko liczymy.
- **Kadry przed katalogiem.** Pole zmienione ręcznie w NEXUSIE
  (`profile_created`/`profile_updated` w `hr_audit_events`, także kreator
  wejścia) po ostatnim zapisie tego pola z M365 jest przypięte — katalog go nie
  nadpisuje. Kadry odpinają pole, czyszcząc je (puste pole zawsze wypełnia
  katalog). Pusty atrybut w katalogu niczego nie kasuje. Wartości z importu
  Compassa nie są ręczne, więc pierwsza synchronizacja je odświeża. (Compass
  nadpisywał ręczne zmiany co tydzień — błąd naprawiony.)
- Ślad `profile_m365_synced` tylko przy zmianie, z samymi nazwami pól;
  `m365_synced_at` stempluje każdy udany odczyt.
- Tryby: `off` nic; `simulate` buduje te same żądania, ale nie wysyła ich i nie
  zmienia kartoteki (wynik: liczba kont i wzór żądania, bez adresów); `live`
  czyta tylko konta z `HR_M365_MAILBOX_ALLOWLIST` (pusta = wszystkie).
- 404 = konto spoza tenanta → pomijamy i liczymy (`not_found`). 403 albo brak
  tokenu = przebieg `failed` (sonda `hr_m365`: `degraded: profile_sync_forbidden`),
  ponowienie przy kolejnym obrocie pętli (co godzinę).

### Termin sekretu rejestracji (`m365/secret_expiry.py`)

- Termin podajemy sami: `HR_M365_CLIENT_SECRET_EXPIRES_ON` (RRRR-MM-DD, data
  „Expires” z Entra ID). Pusta albo nieczytelna wartość = „nie znamy”, nigdy
  błąd startu.
- **Rotacja:** nowy sekret w Entra ID (rejestracja „NEXUS Kadry”) →
  workflow „Coolify set env” ustawia RAZEM `HR_M365_CLIENT_SECRET`
  i `HR_M365_CLIENT_SECRET_EXPIRES_ON` → stary sekret usunąć po wdrożeniu
  (okno 19:00–07:00) i sprawdzeniu `/api/health`.
- Sonda `hr_m365`: ≤ 30 dni `degraded: secret_expires_in_<n>d`, w dniu terminu
  i po nim `unhealthy: secret_expired` (uptime-probe otwiera zgłoszenie),
  brak daty przy rejestracji pracującej na żywo (urlopy, Intune albo czytnik
  administracja@) `degraded: secret_expiry_unknown`.
- Alarm `automation_failing` (tylko admini, mail od razu) od 7:00, raz przy
  progu 30, 14, 7, 1 dnia i raz w dniu terminu — klucz rezerwacji (termin,
  próg), więc nowa data po rotacji zaczyna od nowa. Karta „Microsoft 365”
  w Ustawieniach → Kadry pokazuje termin i ostatni odczyt profili, a nad kartą
  ostrzeżenie przy ≤ 30 dniach, po terminie i przy braku daty.

## „Mój miesiąc” — obecność i godziny (`app/services/hr/time_*.py`)

- Jeden ekran: siatka miesiąca z obecnością (tylko wyjątki od domyślnego miejsca
  pracy) i godzinami. Limit 8 h liczony na SUMĘ wpisów dnia pod blokadą wiersza
  timesheetu; ponad 8 h (do 16 h) to nadgodziny — tylko z prawem
  (`can_log_overtime`, Kadry, admin) i z uzasadnieniem. Pełny dzień urlopu
  blokuje wpis, pół dnia zajmuje 4 h; płatny urlop B2B z puli to auto-wpis.
- Przejścia: szkic → wysłany → zaakceptowany; zwrot do szkicu z notatką; cofnięcie
  akceptacji. Nikt nie akceptuje własnego timesheetu (CHECK `approved_by <> user_id`).
- **`pdf_hash` = funkcja Compassa co do bajtu** (`time_hash.py`, sortowanie jak
  w JavaScripcie, `toFixed(2)`). Zmiana algorytmu = każdy zaimportowany PDF zgłosi
  rozbieżność. Wektory w `tests/test_hr_time_hash.py` policzono kodem Compassa.
  Pobranie PDF przy rozjeździe sumy = 409.
- `payroll_locked` (zamknięty miesiąc płac) blokuje każdą zmianę timesheetu,
  także nowo zakładanego (`ensure_timesheet` czyta `payroll_periods.is_closed`).
- **Odczyt bez zapisu** (17.10.2026): `GET` „Mojego miesiąca” niczego nie
  zapisuje. Bez timesheetu widok pokazuje szkic wirtualny (z auto-wpisami
  płatnego urlopu), a wiersz `timesheets` zakłada pierwszy zapis
  (`time_entries.open_draft`: wpis, „Wypełnij miesiąc”, wysyłka). Wysyłka
  w zamkniętym miesiącu bez timesheetu = 409.
- **Potwierdzenie godzin na zleceniu** (D7, art. 8b/8c): przyjęty raport osoby
  na zleceniu po terminie wypłaty (koniec miesiąca następnego) zostaje bez zmian
  3 lata (`time_retention.py`): cofnięcie przyjęcia i usunięcie wpisu = 409,
  zgłoszona później nieobecność nie zdejmuje godzin (miesiąc jak zamknięty
  w płacach — ostrzeżenie osobie, powiadomienie Płacom). Przed terminem
  wypłaty to zwykła korekta. Decyduje forma zapisana przy akceptacji
  (`timesheets.employment_type`), nie obecna; stare wiersze bez niej — obecna.
  Wiersza `timesheets` nie kasuje żadna ścieżka (`user_id ON DELETE RESTRICT`,
  odejście i wyłączenie konta nie ruszają godzin).
- PDF: tytuł z formy — „Ewidencja czasu pracy”, „Raport godzin”, „Potwierdzenie
  liczby godzin” z dopiskiem o art. 8b; role „Pracownik/Wykonawca/Zleceniobiorca”.
- **Luki z Compassa domknięte przed 1.11.2026 (18.10.2026):**
  - „Wypełnij miesiąc” ma okno: godziny dziennie (domyślnie 8, powyżej 8 = 422 —
    nadgodziny tylko wpisem dnia z uzasadnieniem), opis (domyślny roli / szablon /
    własny), projekt i „nadpisz istniejące wpisy” (kasuje wpisy szkicu poza
    auto-wpisami płatnej puli; blokada retencji jak przy usuwaniu wpisu). Dzień
    dostaje najwyżej tyle, ile zostawia urlop (pół dnia urlopu = 4 h; pół dnia
    płatnej puli B2B = auto-wpis 4 h + 4 h z wypełniania). Tylko dni
    zatrudnienia z kartoteki (`work_start_date`–`last_working_day`, też
    w `days_missing`). Poprawka samego opisu albo projektu wpisu nie przelicza
    nadgodzin dnia (audyt 19.10.2026).
  - Domyślny opis dnia (bez opisu roli i szablonu; też auto-wpis płatnej
    puli) to słowo formy `standard_description`: B2B i zlecenie „Realizacja
    usług zgodnie z umową”, UoP „Praca standardowa” (decyzja Artura
    28.10.2026). Stare wpisy zostają; przepisane były tylko szkice X/2026
    (`scripts/timesheet_standard_description_rewrite.py`, podgląd →
    `--apply`). Raportów z `pdf_hash` nie przepisuje się — hash liczy opis.
  - „Szablony opisów” osoby (dodaj, edytuj, usuń, kolejność = `sort_order`)
    i karta „Domyślne opisy godzin” w Ustawieniach → Kadry (role NEXUSA bez
    `user`/`sourcer`/`tac`) — na istniejących trasach `/api/hr/time/me/templates`
    i `/api/hr/time/role-defaults`.
  - Eksport CSV (`services/hr/time_export.py`): własny
    (`/me/export.csv`), osoby (`/people/{id}/export.csv`, bramka jak PDF)
    i miesiąc zespołu (`/export/{r}/{m}/csv`, bramka jak ZIP, każdy status).
    Separator `;`, przecinek dziesiętny, UTF-8 z BOM, bez kwot, `safe_row`,
    najwyżej 24 miesiące; eksport cudzych godzin zostawia ślad
    `timesheet_csv_exported`. Bez prawa do rodzaju nieobecności auto-wpis puli
    to „wpis automatyczny” (D6).
  - „Składa raport godzin” (`timesheet_required`) hurtem w katalogu „Ludzi”
    (`POST /api/hr/admin/profiles/timesheet-required`, Kadry/admin, ślad per
    osoba). Domyślnie `true` dla każdej kartoteki — przypomnienia 1.–5. idą
    tylko do osób z flagą, więc przed pierwszym miesiącem w NEXUSIE Kadry
    ustawiają listę (Compass pomijał B2B).

## Płace i premie (`app/services/hr/payroll_*.py`, `bonus_rules.py`)

- D2: Płace (Finanse z roli, admin) widzą stawki i kwoty u wszystkich; osoba —
  swoje; przełożony — godziny i premie swoich bezpośrednich podwładnych, bez stawek
  i kwot wynagrodzenia. Nikt nie przyznaje premii sobie.
- Stawki z historią, obowiązują od 1. dnia miesiąca. Automat premii (placementy,
  Liga) i zmiana albo usunięcie stawki blokują okres płac współdzielonie przed
  własnymi wierszami (trwające zamknięcie miesiąca czeka albo daje 409).
- Nowa stawka domyka dniem przed sobą tylko stawkę, która w jej dniu trwa
  (`rate_to_close`); stawka zakończona wcześniej (luka z importu Compassa) zostaje,
  a luka daje ostrzeżenie `missing_rates` (19.10.2026).
- Kwoty premii i stawek zaokrąglane HALF_UP jak raport płac; zakres premii
  (0,01–1 000 000) sprawdzany na kwocie po zaokrągleniu — 0,004 to 422, nie 500
  (19.10.2026).
- Zatwierdzenie propozycji z placementu: uzgodnienie kontraktu (z commitem) biegnie
  dopiero, gdy widz może o premii zdecydować; obcy dostaje 404 bez zapisu. Logi
  automatu premii niosą klasę wyjątku, nie treść (DETAIL Postgresa pokazuje kwoty
  wiersza) (19.10.2026).
- **Własnej stawki nie ustawia ani nie usuwa osoba z Płac** (decyzja Artura
  19.10.2026, `payroll_rates.ensure_not_own_rate`): 403 „Własnej stawki nie
  ustawiasz / nie usuwasz — zrobi to druga osoba z Płac albo administrator.”;
  administrator może (ślad w audycie jak zawsze). Na własnej kartotece
  `can_edit_rates = false`.
- **Premia ręczna od przełożonego to propozycja** (decyzja Artura 19.10.2026,
  `payroll_bonuses.approval_refusal`): powstaje jako `proposed` (bez `assigned_by`,
  ślad `bonus_proposed`, bez dzwonka osobie); zatwierdzają ją tylko Płace, nigdy jej
  autor (403), dzwonek „Masz nową premię” idzie przy zatwierdzeniu. Autor może ją
  zmienić albo wycofać. Płace przyznają od razu jak dotąd. Listy premii niosą
  `can_approve` — front pokazuje „Zatwierdź” tylko wtedy, a po dodaniu przełożony
  widzi „Premia czeka na zatwierdzenie Płac”. Zamknięcie miesiąca i tak wymaga decyzji.
- **Po zatwierdzeniu przez Płace przełożony nie zmienia kwoty, ale może anulować
  premię, którą sam przyznał** (decyzja Artura 22.10.2026, audyt 22.10 F15):
  `update_bonus` daje mu 403 „Przyznaną premię zmieniają Płace” (audyt 21.10.2026),
  a `cancel_bonus` przepuszcza autora w każdym stanie przy otwartym miesiącu —
  osoba dostaje dzwonek „Premia została anulowana”. Ekran pokazuje wtedy przy
  przyznanej premii samo „Anuluj” (`payroll-format.assignedBonusActions`);
  „Zmień” zostaje tylko przy propozycji i u Płac.
- Trwałe usunięcie kontraktu anuluje jego propozycje premii automatu
  (`cancel_reason='contract_deleted'`, automat ich nie przywraca); przyznane zostają.
- Premie: `source` manual / contract_placement / league / compass_import,
  `source_key` unikalny (automat nie dubluje), `rule_snapshot` przy naliczeniu.
  Termin premii z placementu = start kontraktu + 21 dni roboczych firmy (święta
  ustawowe i dni wolne firmy — ten sam kalendarz co urlop, decyzja 17.10.2026);
  premia DL = 10% × marża/h × 168 h; rekruter progami marży PLN/h. Progi
  i „dodatkowa premia DL” to ustawienia (`app_settings['hr_bonus_rules']`),
  w kodzie nie ma żadnej osoby.
- **Odbiorcy premii z placementu jak w Compassie** (decyzja Artura 18.10.2026,
  `PlacementContext.people`): rekruter = osoba, która jako pierwsza zweryfikowała
  kandydata w rekrutacji kontraktu (etap „Zweryfikowany”, kolejność jak w KPI:
  `approved_at`, potem `moved_at`); bez weryfikującego premii rekrutera nie ma.
  Prowadzący (`jobs.recruiter_id`) nie jest odbiorcą — w rekrutacjach sprzed
  10.2026 siedzi tam zwykle Delivery Lead (porównanie IX 2026: 19 z 27) i jako
  rekruter nie dostaje premii. DL = `jobs.delivery_lead_id`; gdy pusty —
  prowadzący (`jobs.recruiter_id`), jeśli ma rolę Delivery Leada (główną albo
  dodatkową, `people_source = job_lead`); dopiero potem DL klienta (głowa albo
  jedyne przypisanie). Z tym krokiem DL zgadza się z Compassem w 24 z 27
  placementów IX 2026 (bez niego 17). Prognoza „w drodze” szuka kontraktów
  osoby po tej samej regule.
- **`automation_since`** w `hr_bonus_rules` oddziela placementy Compassa od
  automatu NEXUSA: premie z Compassa wchodzą importem (`compass_import`, klucz
  `compass:<uuid>`), automat ma klucz `contract:<id>:<rola>` — bez daty
  granicznej automat w oknie 120 dni wstecz zaproponowałby je drugi raz. Ta sama
  data odcina Ligę: okres kończący się przed nią nie trafia do płac.
  Strażnik (audyt 19.10.2026): przy premiach `compass_import` w bazie `PUT /rules`
  odmawia (422) pustej daty i daty wcześniejszej niż zapisana; zepsuty wpis
  `hr_bonus_rules` daje reguły domyślne, ale z zapisaną datą (nieczytelna data =
  automat nie zakłada nowych propozycji), nigdy okno 120 dni.
- Zakończenie kontraktu przed terminem anuluje premię, cofnięcie zakończenia ją
  przywraca (`app/services/hr/contract_hooks.py`).
- Zamknięcie miesiąca: propozycje premii muszą mieć decyzję, ostrzeżenia wymagają
  potwierdzenia, linie zamrożone w `payroll_lines`, timesheety zablokowane.
  Ponowne otwarcie tylko admin, z powodem. Zamknięcie blokuje okres i timesheety
  PRZED liczeniem raportu; akceptacje timesheetów i premii sprawdzają okres pod
  blokadą współdzieloną (kolejność: okres, potem timesheet).
- **Ponowne zamknięcie po opłaconym rozliczeniu** (decyzja Artura 19.10.2026): gdy kwota
  osoby z rozliczeniem już opłaconym różni się od tej zapłaconej, zamknięcie odmawia
  (409 `paid_settlement_changed`, bez potwierdzania) — różnica nie miałaby przelewu;
  zmianę (np. premię) przenosi się na kolejny miesiąc. Premia przyznana po zapłacie
  nie jest „wypłacona” (`paid_flags` porównuje `assigned_at` z `paid_at`).
- **Premia przyznana, kontrakt zakończony przed terminem** (np. zamknięty w systemie datą
  wsteczną po zatwierdzeniu; decyzja Artura 19.10.2026): automat jej nie anuluje, ale widok
  miesiąca Płac i zamknięcie dają ostrzeżenie `bonus_contract_ended_early` (do
  potwierdzenia), a premia na liście ma znacznik „premia przepada” (`contract_ended_early`).
- Urlop zatwierdzony albo anulowany w zamkniętym miesiącu płac: odpowiedź API niesie
  `payroll_locked_months` i `payroll_warning` (front pokazuje je w komunikacie), Płace
  dostają powiadomienie i mail bez rodzaju nieobecności, ślad z `sensitivity="payroll"`.
- Dzień wolny firmy dodany albo usunięty przelicza dni aktywnych wniosków obejmujących
  tę datę (pula wraca), powiadomienie i mail osobie (mail bez słowa „urlop”); okno M365 bez zmian.
- Cofnięcie zakończenia kontraktu przywraca premię z zamkniętego miesiąca jako
  propozycję w pierwszym otwartym miesiącu (`restored_from_closed_period`).
- Import z Compassa: koniec stawki minus jeden dzień (Compass trzyma pierwszy dzień
  następnej stawki); ponowny import nie nadpisuje zmian zrobionych w NEXUSIE po
  poprzednim zapisie (`unchanged` albo `conflict`, nigdy `update`) — także fragmentów
  opisu, domyślnych opisów ról i wpisów timesheetu; timesheet zablokowany płacami
  jest nietykalny.

- **Ekran zamknięcia miesiąca (makieta „Płace — zamknięcie miesiąca”, 19.10.2026,
  `PayrollCloseParts.tsx`, czyste funkcje w `payroll-format.ts`).** Stepper
  Godziny → Premie → Kontrola → Zamknij (`closeSteps`) blokuje tylko to, co blokuje
  serwer: każda propozycja premii z okresu (także „liczy się”, `stats.proposals`)
  i niepotwierdzone ostrzeżenia. Godziny bez akceptacji to krok żółty (ostrzeżenie
  `unapproved_timesheets`), potwierdza się je w „Kontroli” („Potwierdzam
  ostrzeżenia”), a zamknięcie idzie wtedy od razu z `acknowledge_warnings`.
  „Zamknij miesiąc” jest widoczne w otwartym miesiącu i nieaktywne do końca kroków
  (podpowiedź mówi, czego brakuje). „Razem do wypłaty” liczy z linii osób
  (`payoutBreakdown`: godziny i premie per waluta, per forma) — te same kwoty co
  raport płac, nic nowego po stronie serwera. Osoba „do wyjaśnienia”
  (`needsAttention`) = raport bez akceptacji (gdy go składa) albo godziny bez
  stawki; wiersz podświetlony, filtr „Do wyjaśnienia N”. Przełożony widzi dawny
  układ (liczby, tabela bez stawek, decyzje wiersz po wierszu) — D2 bez zmian.
- **„Zatwierdź zaznaczone”** (`POST /api/hr/payroll/bonuses/approve-batch`,
  `{ids: [1..100]}`, bramka `require_hr_payroll_admin` — tylko uprawnienie „Płace”,
  przełożony 403). Wszystko albo nic w jednej transakcji żądania: każda premia
  przechodzi `payroll_bonuses.approve_bonus` (zakres, autor propozycji ręcznej,
  termin, otwarty okres, dzwonek osobie); pierwsza odmowa cofa całość (także
  dzwonki) i odpowiada jej kodem z „Nic nie zatwierdzono — premia: <osoba>. …”.
  Uzgodnienie kontraktów biegnie wcześniej i zostaje (jak przy pojedynczym).
  Id sortowane rosnąco (stała kolejność blokad wierszy), duplikaty łączone. Na
  ekranie domyślnie zaznaczone wszystko, co da się zatwierdzić
  (`batchSelectable`: po terminie, `can_approve`, nie własna), z sumą per waluta
  i oknem potwierdzenia przed wysłaniem.
- **„Przypomnij” o raporcie godzin** (`POST /api/hr/time/remind/{user_id}/{rok}/{miesiąc}`,
  `time_reminders.remind_one`, bramka `require_hr_time_reminder`: Płace, Kadry,
  admin albo akceptujący — przełożony, zastępca, head pionu). Szkic albo brak
  raportu → osoba (`hr_timesheet_reminder`, słowa formy, termin wysłania); raport
  wysłany → akceptujący z `approval_recipients` bez wołającego
  (`hr_timesheet_submitted`, link do „Akceptacji”). Raz dziennie na osobę, miesiąc
  i adresata (`hr_job_runs` `hr_timesheet_manual_reminder`,
  `RRRR-MM:u<id>:<person|approver>:<dzień>`) — drugi klik odpowiada 200
  `already_today: true` i nic nie wysyła. Odmowy: sobie 403; osoba spoza zakresu
  404; przyjęty raport, miesiąc zamknięty w płacach, osoba bez obowiązku raportu,
  wyłączone konto i „czeka na Twoją decyzję” (wołający jest jedynym
  akceptującym) — 409. Ślad `timesheet_reminder_sent` w `hr_audit_events`.
  Odpowiedź: `{target, status, sent, already_today}`; front: `useRemindTimesheet`
  + `reminderToast` w `lib/api/hr-time.ts` (z nich korzystają też „Akceptacje”).
  W Płacach „Przypomnij” przy szkicu i braku, „Ponagl przełożonego/koordynatora”
  przy raporcie do akceptacji (tylko Płace — przełożony sam akceptuje).
  W „Akceptacjach” (sekcja „Timesheety”, 20.10.2026) „Przypomnij” jest przy
  szkicu i braku raportu (`canRemindInQueue`), przy „do akceptacji” zostaje
  „Akceptuj”. Godziny to „72 / 176 h” z paskiem — norma z pola `norm_hours`
  odpowiedzi `GET /api/hr/time/team/{rok}/{miesiąc}` (kalendarz firmy × 8 h, ta
  sama co w „Moim miesiącu”). Lista zwinięta do 5 wierszy (najpierw brak
  raportu, potem do akceptacji, szkice, zaakceptowane) z „Pokaż wszystkie (N)”.

## „Mój czas” — przegląd, saldo, premie w drodze, rozliczenie (etap 2, 17.10.2026)

- **„Przegląd” jest pierwszą i domyślną zakładką** „Mojego czasu” (`?tab=overview`,
  inne wartości `?tab=` jak dotąd; link z powiadomienia `?tab=bonuses` działa).
  Karty: nieobecności, miesiąc, premie, „Ja w firmie”, sprzęt, do zrobienia
  (`components/hr/me/MyOverviewTab.tsx`). **Bez zakładki „Kartoteka”**
  (21.10.2026, runda 2 makiet): stanowisko, przełożony / koordynator i link
  „Otwórz kartotekę” są w karcie „Ja w firmie” (pula — tylko przy zamkniętym
  module nieobecności); stary `?tab=profile` otwiera „Przegląd”. Klik
  w zakładkę zapisuje `?tab=` w adresie (`useUrlWriter`). Karta modułu wyłączonego nie istnieje
  i nie pyta serwera; awaria zapytania to zdanie z „Spróbuj ponownie” w karcie,
  nigdy „0”.
- **Forma zatrudnienia decyduje o słowach** (B2B i zlecenie nie mają urlopu
  w rozumieniu Kodeksu pracy; decyzja Artura 17.10): UoP → „Urlop RRRR”
  z „na żądanie X z 4” i „opieka nad dzieckiem X z 2”; B2B (i zlecenie)
  z płatną pulą > 0 → „Płatne dni przerwy (z umowy)” bez limitów Kodeksu;
  bez płatnej puli → „Nieobecności RRRR” bez „zostało”. Karta miesiąca:
  UoP „Ewidencja czasu pracy”, B2B „Raport godzin”, zlecenie „Potwierdzenie
  godzin” ze zdaniem o art. 8b ustawy o minimalnym wynagrodzeniu. Te same
  reguły w saldzie zakładki „Urlopy” — od 21.10.2026 (runda 2 makiet) zakładka
  pokazuje tę samą kartę `AbsenceCard` co „Przegląd” i obok „Mój rok”
  (`yearMonths`: 12 miesięcy z moimi zatwierdzonymi i czekającymi
  nieobecnościami; święta i dni firmy czyta tylko trasa Kadr). Funkcje:
  `components/hr/me/overview-format.ts`.
- **Saldo rozbite** (`GET /api/hr/leave/balance`, `leave_balance.day_split`):
  `used_days` = dni sprzed NEXUSA + zatwierdzone do dziś włącznie (dzień
  nieobecności trwający dziś już się liczy), `planned_days` = zatwierdzone po
  dziś, `pending_days` = czekające. Przy płatnej puli liczą się dni płatne
  i z `remaining_days` sumują się do puli z zaległym; „zostało” dalej odejmuje
  oczekujące. Bez płatnej puli (`has_paid_pool = false`: brak puli, pula 0)
  trzy liczby to wszystkie dni rodzajów puli (bez wynagrodzenia), `remaining_days
  = null`. Dzień liczy się do roku SWOJEJ daty (urlop przez Nowy Rok — dwie
  pule). `approved_days` zostaje (czyta je Jarvis).
- **Premie „w drodze” od podpisania umowy (D2).** Podpisana umowa przed startem
  to kontrakt `active` z przyszłym startem (podpis aktywuje go od razu).
  Automat zakłada propozycję, gdy zna marżę; bez stawki klienta (przychodzi
  z zamówieniem) propozycji nie ma. `GET /api/hr/payroll/me` niesie `forecast`
  (`services/hr/my_settlement.bonus_forecast`): kontrakty `active`/`ending`
  w oknie automatu, przed terminem premii, bez końca przed terminem, bez
  „powrotu po przerwie”, a odbiorcy i kwoty z tej samej czystej funkcji co
  automat (`placement_bonuses.placement_targets`), termin `eligible_date`,
  postęp `business_days_elapsed`. Pozycja, dla której automat ma już wiersz
  premii (w dowolnym stanie), do prognozy nie trafia. Kwota to szacunek („~”);
  bez stawek albo kursu NBP `amount = null` z `amount_missing_reason`. Nic nie
  jest zapisywane.
- `/me` zwraca premie w każdym stanie — **anulowane przez automat zostają**
  z `cancel_reason` (Compass i pierwsza wersja ekranu je chowały), przyznane
  mają `assigned_by_name`, każda `period_closed` (miesiąc zamknięty w płacach =
  rozliczona), propozycja przed terminem — postęp „X z 21 dni” tą samą funkcją
  co widok miesiąca płac (`_add_progress`). Ekran „Premie i stawka” pokazuje
  etapy: umowa → 21 dni → decyzja Płac → wypłata (`BonusStagesTable`).
- **„Moje rozliczenie” (D3)**: `GET /api/hr/payroll/me/settlement?year=`
  (bramka `require_hr_payroll_member`, 403 bez własnej kartoteki — także Płace
  i przełożony bez kartoteki). Miesiąc zamknięty = zamrożone `payroll_lines`
  osoby (`final = true`); otwarty = szacunek regułą raportu płac: stawka z 1.
  dnia miesiąca × suma wpisów timesheetu z „Mojego miesiąca” (zaakceptowanego
  albo w toku — `hours_source` `approved`/`entered`) + premie przyznane
  z okresem w tym miesiącu. Płace przy zamknięciu biorą tylko godziny
  zaakceptowane, więc szacunek zmienia się do zamknięcia. Tylko o sobie.
- **Przełom roku i kolejność kart „Rozliczenia”** (audyt A2, 19.10.2026). Ekran
  nie ma wyboru roku: „Rozliczenie” pyta zawsze o bieżący i poprzedni rok —
  w styczniu pokazuje cały poprzedni, potem tylko jego miesiące, w których osoba
  ma coś do zrobienia (`awaiting_document` albo `mismatch` z prośbą o korektę).
  „Premie i stawka” w styczniu dokłada poprzedni rok do „Mojego rozliczenia”,
  a „premie wypłacone” są wtedy za poprzedni rok (styczeń zamyka się w lutym).
  Na górze miesiące do działania (z „Kopiuj pozycje” i kartą faktury), potem
  najnowszy; wiersze miesiąca w kilku walutach są razem (`settlementLayout`
  w `components/hr/me/settlement-format.ts`).
- **Archiwum timesheetów** w „Moim miesiącu” (`TimesheetArchive`): ostatnie
  12 miesięcy ze statusem, sumą godzin i PDF zaakceptowanego
  (`GET /api/hr/time/me/history`), pobierane dopiero po rozwinięciu.
- **Układ „Przeglądu” po makiecie (19.10.2026).** Górny rząd: pierścień
  nieobecności (`ringArcs`: wykorzystane → zaplanowane → czeka, w środku
  „zostało”; bez płatnej puli — liczby bez pierścienia), miesiąc z paskiem godzin
  (`monthHoursPercent`: praca + płatna nieobecność wobec normy) i mini-kalendarzem
  (`monthCalendar`: uzupełniony, zdalnie, nieobecność, brakujący do dziś jako
  przycisk otwierający „Mój miesiąc”, przyszły, wolny; osoba bez obowiązku raportu
  nie ma dni „do uzupełnienia”), premie jako oś (`MyBonusItem.progress` i
  `timeline`: „14 z 21 dni · liczy się do 28.10”, prognoza „umowa podpisana ·
  start … · liczy się do ~…”). „Liczy się do” to termin decyzji Płac, nie dzień
  wypłaty — nie pisz „wpadnie”. Dolny rząd: „Do zrobienia” (termin jako pigułka
  `due`, jedna akcja `action`; protokół sprzętu bez przycisku — podpis idzie
  linkiem z maila), „Mój sprzęt” (`EquipmentCard`, własna karta z ikoną rodzaju;
  404/403 chowa kartę) i koordynator z pierścieniem „w pracy / nieobecny” tylko
  przy otwartym module nieobecności.
- Harness `/preview/hr-my-time`: domyślnie „Przegląd” osoby B2B z umowną pulą,
  `?form=uop`, `?form=zlecenie`; zero żądań pilnuje
  `app/preview/__tests__/hr-my-time-harness.test.tsx`.

## Rozliczenia zespołu — faktury z KSeF, przelewy, Symfonia (etap 4, R1–R12, 17.10.2026)

Moduł `settlements` (domyślnie wyłączony). NEXUS nie liczy podatków ani składek —
kwota oczekiwana to zamrożona linia płac; netto, PIT, ZUS i PPK liczy Symfonia.
Schemat: `hr_settlement_schema.py` (migracja `0468_hr_settlements`, stany w docstringu).

- **Rozliczenie** (`payroll_settlements`) powstaje przy zamknięciu miesiąca z każdej linii
  z kwotą > 0 (`payroll_close` → `settlements.ensure_for_period`); miesiąc zamknięty przed
  włączeniem modułu — `POST /api/hr/settlements/months/{r}/{m}/prepare`. Ponowne otwarcie
  anuluje nieopłacone (opłacone zostają), faktury wracają do `unmatched` z osobą.
  Zamknięcie i otwarcie miesiąca w Płacach odświeżają na froncie także rozliczenia
  i przelewy („Dla Finansów”, podgląd Symfonii), a każda decyzja w rozliczeniu —
  przelewy (audyt A2, 19.10.2026).
- **Od którego miesiąca** (decyzja Artura 19.10.2026): `hr_payment_settings.settlements_since`
  („RRRR-MM”, produkcja `2026-10`). Miesiące wcześniejsze to archiwum Compassa: zamknięcie
  przechodzi bez rozliczeń, `prepare` = 422, a premia z nich jest wypłacona przy zamkniętym
  miesiącu (reguła sprzed modułu — `paid_flags`, „Moje rozliczenie”). Brak albo zła wartość =
  bez progu. Klucza nie ma w formularzu Ustawień — ustawia go operacja na produkcji.
- **B2B:** `awaiting_document` → `ready` przy netto faktury równym linii co do grosza
  i rachunku z białej listy, inaczej `mismatch`. Netto = faktura pierwotna + korekty
  (korekta FA(3) zapisana jako różnica; dopina się tylko do faktury tego samego sprzedawcy).
  Termin = dzień nadania numeru KSeF + `payment_terms_days` osoby (domyślnie 14).
  **Zlecenie i UoP:** od razu `ready`, termin = `app_settings['hr_payment_settings']['payout_day']`
  (domyślnie 10.) miesiąca po okresie; PDF rozliczenia zlecenia zamiast rachunku (R3).
- **Druga osoba:** „Uznaj różnicę” (kwota albo rachunek spoza białej listy) potwierdza ktoś
  inny z Płac/Finansów/admin; nowy dokument albo zmiana rachunku kasują uznanie. Nikt nie
  zatwierdza ani nie oznacza zapłaty własnego rozliczenia. R11: przy włączonym module premia
  „wypłacona” dopiero z opłaconym rozliczeniem (`payroll_bonuses.paid_flags`).
  Własne rozliczenie także z wyciągu i paczki (19.10.2026): wiersz wyciągu dopasowany do
  rozliczenia importującego zostaje `unmatched` (powód `own_settlement`, przypisuje inna
  osoba), „Bank wykonał” z własnym nieopłaconym rozliczeniem w paczce = 409
  `own_settlement_in_batch` dla całej paczki (bez opłacania w połowie).
  Ręczne „opłacono” i „Przypisz” z wyciągu (decyzja Artura 19.10.2026, „Ogranicz”):
  rozliczenie czekające na dokument albo z problemem bez potwierdzonego uznania
  (`payment_state_refusal`) = 409 `settlement_not_payable` — najpierw „Uznaj różnicę” drugą
  osobą albo właściwy dokument; B2B z kwotą ≠ brutto faktur (pierwotna + korekty) o więcej
  niż 0,01 = 422 `paid_amount_differs` z obiema kwotami. Zlecenie i UoP bez zmian (kwota na
  rękę z Symfonii). `can_mark_paid` w kolejce idzie za tą regułą. Automatyczne dopasowanie
  z importu wyciągu tej reguły nie ma (osobna decyzja).
- **Zmiana odbiorcy** (rachunek albo NIP) cofa zatwierdzenie i kasuje uznanie KAŻDEGO rodzaju;
  sama zmiana terminu nie. Uznanie rachunku nie obejmuje późniejszego problemu z kwotą.
  Problem `gross` (jak różnica kwoty, druga osoba): brutto ≠ netto + VAT (> 0,01), VAT > 0 przy
  statusie VAT ≠ `active`, VAT > 23% netto; faktur z KSeF nie odrzucamy, ręczny PDF tak.
  Faktura z KSeF łączy się z wcześniej dopiętym PDF-em (ten sam NIP, numer, waluta) zamiast
  liczyć się drugi raz; dopasowaną, nieopłaconą Płace mogą odpiąć („Pomiń”, „Przenieś”).
  Problem `seller` (19.10.2026): dopasowana faktura od innego NIP-u niż w danych do
  rozliczeń (same cyfry; brak NIP-u w danych przy fakturze z NIP-em też) = `mismatch`.
  Żadne uznanie go nie obejmuje i „Uznaj różnicę” odmawia (409) — to zła faktura albo złe
  dane, nie różnica: odpiąć fakturę albo poprawić NIP. Bo zmiana NIP-u + rachunek z wykazu
  dla nowego NIP-u przepuszczały starą fakturę jako „Do zapłaty” bez drugiej osoby.
  Dzwonki rozliczeń idą bez numeru encji (dzienny odsiew powiadomień nie zna jej rodzaju).
- **Dane do rozliczeń** (`employee_billing_details`): osoba (odczyt), Kadry, Płace, admin;
  przełożony i zespół — 404. Rachunek szyfrowany (`TokenCipher`), na zewnątrz tylko 4 cyfry;
  NIP unikalny między osobami (409); identyfikator osoby w Symfonii zamiast PESEL-u (PESEL
  odrzucany). Rachunek nigdy w logach, śladzie ani komunikatach błędów.
- **KSeF** (`services/hr/ksef/*`, `KSEF_MODE=off|test|demo|prod`, lokalnie `simulate`):
  token KSeF spółki (`KSEF_TOKEN`, uprawnienie `InvoiceRead`) + `KSEF_CONTEXT_NIP`; brak =
  wyłączone. Pobieranie przyrostowe od znacznika HWM (`app_settings['hr_ksef_sync']` per
  środowisko i NIP), co godzinę (`hr_job_runs`), najwyżej 8 zapytań o metadane i 40 pobrań na
  przebieg, „Pobierz teraz” co 5 minut. **Do rozliczeń zapisujemy wyłącznie faktury od NIP-ów
  z danych do rozliczeń** — reszta to licznik „pominięte”; po dopisaniu NIP-u „Pobierz ponownie
  okres”. Przy włączonym module „Zgody” reszta to faktury kosztowe spółki, zapisywane z samych
  metadanych do „Wydatków ze zgodą” (licznik `costs`, bez pobrania XML-a; 0486,
  `ludzie/zgody-wydatki-i-premie-poza-umowa.md`).
  Samego XML-a nie trzymamy, tylko skrót. Klient obsługuje Subject1 i Subject2 (etap 5).
- **Biała lista** (`white_list.py`, `WHITE_LIST_MODE=off|test|live`, lokalnie `simulate`):
  `search`/`check` z pamięcią wyników na dzień i limitem 100 zapytań; brak odpowiedzi =
  `WhiteListError` (nigdy „na liście”). Identyfikator zapytania zapisany przy rachunku.
- **Przelewy** (`services/hr/bank/*`, `/api/hr/payments`): domyślnie ekran „Dla Finansów”
  (zatwierdzone do zapłaty + CSV z 4 cyframi rachunku + lista NIP-ów dla reguły w eBI24) i import
  wyciągu MT940/CAMT.053 → `settlements.mark_paid`. Z wyciągu zapisujemy tylko przelewy do
  ludzi z zespołu; zlecenie/UoP opłacone z wyciągu tylko z miesiącem w tytule, inaczej decyzja
  Płac; drugi przelew tej samej faktury → decyzja Płac. Paczka przelewów Elixir-O/CSV to
  opcja wyłączona domyślnie (format nie sprawdzony w banku firmy); pozycja bez pozytywnego
  `white_list.check` jest zablokowana do decyzji Finansów. Wiersz paczki pamięta skrót HMAC
  pełnego rachunku (klucz wyprowadzony z `M365_TOKEN_ENCRYPTION_KEY`) — podmiana rachunku po
  utworzeniu paczki = 409 `batch_account_changed` przy pobraniu pliku.
  Wyciągi (19.10.2026): plik z kilkoma wyciągami — waluta operacji z jej wyciągu (MT940:
  `:60F:` przy `:61:`, CAMT: `Amt/@Ccy`, bez niego `Acct/Ccy` tego `Stmt`). Storno: kierunek
  = `CdtDbtInd` wpisu (CRDT + `RvslInd` = wpływ, np. zwrot nieudanej wypłaty — nie opłaca
  rozliczenia), jak `RC`/`RD` w MT940; kontrahent = strona pierwotnej operacji. CAMT
  z `Ntry/Sts` ≠ `BOOK` (`PDNG`, `INFO`) pomijany; brak `Sts` = zaksięgowany.
- **Symfonia** (`symfonia_export.py`): ZIP z ekranu miesiąca Płac — `zdarzenia_RRRR-MM.xml`
  (windows-1250; L4 tylko, gdy Płace nie pobierają e-ZLA), XLSX premii, XLSX rozliczeń zleceń,
  PDF zestawienia z listą rzeczy do zrobienia ręcznie. Kwoty w paczce tylko dla Płac, plik
  nieobecności tylko Kadry/admin. Słowniki (nazwy zdarzeń, składniki premii) w Ustawieniach → Płace.
  Do potwierdzenia z Płacami: program i wersja, identyfikacja osoby w XML i XLSX, nazwy zdarzeń,
  e-ZLA, szablony importu z Excela.

## Wejście i odejście (`app/services/hr/lifecycle_*.py`, `handover.py`, `deactivation.py`)

- Prowadzą Kadry; przełożony widzi sprawę swojego człowieka; wykonawca odhacza
  swoje zadania. Terminy zadań w dniach roboczych firmy.
- Odejście: przekazanie pracy po 18:00 ostatniego dnia (pięć rodzajów pracy
  przechodzi istniejącymi ścieżkami zapisu — rekrutacje, DL rekrutacji, klienci
  DL, „Moi ludzie”, podwładni), wyłączenie konta dzień później — ale dopiero po przekazaniu
  całej pracy (inaczej „Wyłącz konto teraz” z jawnym „mimo to”, zapisanym w śladzie).
  Sprawy z nieprzekazaną pracą nie da się zamknąć; przejmujący nie może sam odchodzić
  do dnia przekazania. Konto wyłącza wyłącznie sprawa odejścia (nie brak osoby na
  liście), raz na sprawę; admina nie wyłącza automat; przebieg z więcej niż limitem
  deaktywacji nie wyłącza nikogo — kończy się `failed` (`mass_exit_suspected`, sonda
  `hr_jobs` degraded) i powiadomieniem z mailem do Kadr i adminów raz dziennie.
- **Podwładni (etap 2, D5, 17.10.2026)** — piąty rodzaj (`reports`): osoby
  z kartoteką (status ≠ `exited`), których przełożonym jest odchodzący.
  Domyślnie przejmuje przełożony odchodzącego; bez niego — nikt, a wiersz
  z podwładnymi kończy się `failed` jak inne rodzaje (konto czeka, „Wyłącz konto
  teraz” bez „mimo to” = 409). Wykonanie zmienia `manager_user_id` regułami
  kartoteki (`people.validate_managers`, blokada struktury), ślad
  `profile_updated` per osoba (`source: hr_work_handover`). Bezpośredni
  podwładny wskazany jako przejmujący wchodzi na miejsce szefa — dostaje
  przełożonego odchodzącego; ktoś niżej w drzewie = odmowa
  (`receiver_creates_loop`, byłaby pętla). Wnioski i timesheety w toku idą do
  nowego przełożonego, bo akceptującego liczy się w chwili decyzji. Sprawy
  wejścia samych podwładnych (`case.manager_user_id`) przekazanie nie przepina.
- **Przejmujący = obecny przełożony** (17.10.2026): zmiana przełożonego w
  kartotece (edycja, „Struktura”, przekazanie podwładnych) przechodzi na żywą
  sprawę odejścia, gdy sprawa szła za kartoteką, a domyślny przejmujący idzie za
  nim (`lifecycle_service.follow_profile_manager`); przełożony i przejmujący
  wskazani w sprawie ręcznie zostają, zdjęcie przełożonego zostawia przełożonego
  sprawy.
- „Cofnij odejście” zamyka sprawę administracja@ i anuluje zadanie zwrotu sprzętu;
  unieważnienie szkicu kontraktu zamyka sprawę „Wejście konsultanta” i zadanie
  „Przygotuj zestaw”. Zapis szablonu listy zadań zmienia pozycje w miejscu (id) —
  przeliczenie terminów nie dubluje zadań i nie otwiera zrobionych.
- Powód odejścia tylko ze słownika. Obok jest krótka notatka organizacyjna
  (`exit_note`, do 500 znaków) widoczna Kadrom i przełożonemu, z podpowiedzią
  „Bez informacji o zdrowiu” — wolnego tekstu powodu z Compassa
  (`exit_reason_detail`, ankieta) nie importujemy.
- Lista osób dla Compassa: `GET /api/integrations/compass/roster` (zakres
  `people_roster:read`) — bez stawek, premii, nieobecności, powodu odejścia
  i telefonu. Osoby, które odeszły, zostają ze statusem `exited`; pusta lista to
  awaria (503), nie „wszyscy odeszli”. Przy włączonym module `lifecycle` przepływ
  `compass_lifecycle` (NEXUS ciągnął roster Compassa) zwraca
  `superseded_by_hr_lifecycle`.

### Ekrany wejścia i odejścia (makiety 19.10.2026)

- **Kreator wejścia** (`OnboardingWizard`): kroki z opisem; ścieżka kartami
  („Dobierz do formy i działu” + aktywne ścieżki zespołu; „Konsultant u
  klienta” to karta-informacja — wejście konsultanta zakłada kontrakt);
  konto wybiera się wyszukiwaniem z awatarami (`matchAccounts`): najpierw
  konta bez kartoteki, osoby z kartoteką tylko po wpisaniu i bez wyboru.
- **„Co powstanie”** liczy istniejąca trasa podglądu bez zapisu
  (`POST /api/hr/lifecycle/preview`) od pierwszego kroku — bez daty startu
  od dziś, wtedy panel nie pokazuje dat. Zadania pogrupowane wg wykonawcy
  (`previewByOwner`: przełożony, Kadry, recepcja, IT, administracja, osoba…).
- **Odejście** (`OffboardingCaseView`): oś czasu `offboardingMilestones` —
  zgłoszone → rozmowa wyjściowa (zadanie kategorii „Rozmowa”) → przekazanie
  pracy (18:00 ostatniego dnia) → konto wyłączone → sprzęt zwrócony
  (zadania kategorii „Sprzęt”); bez takich zadań kroku nie ma, bieżący =
  pierwszy niezrobiony. „Komu przekazać” (`workLayout`): karty, rozmowy
  u klienta i umówione kontakty idą z rekrutacjami (podpis pod wierszem
  rekrutacji), rodzaje z zerem zwinięte do pigułek, wiersz z wynikiem
  przekazania zostaje zawsze. Zadania pogrupowane wg wykonawcy
  (`groupTasksByOwner`), zrobione na końcu, pasek postępu.

### Ścieżki i wejście konsultanta (etap 3, O1, O4–O6, O11, 17.10.2026)

- **Ścieżki zamiast list** (O1): szablon ma odbiorców (`audience`: `team` —
  zespół wewnętrzny z kontem, `consultant` — konsultant u klienta bez konta)
  i wersję. Pozycja: termin w dniach roboczych, wykonawca (rola: przełożony,
  Kadry, recepcja, IT, osoba, opiekun kontraktu `care_owner`, DL klienta
  `delivery_lead`, administracja `administration` = uprawnienie „Sprawy”),
  opis, „wymagane”, „z plikiem”, warunki (`employment_types`, `equipment`
  `ours`/`client` z `clients.equipment_provider`, `student`) i stały klucz
  (`key`). Warunek zamiast osobnej ścieżki: pozycja pojawia się tylko tam,
  gdzie pasuje. Sprzęt nieznany (klient bez ustawienia) = bez pozycji sprzętu
  (jak hak Sprzętu); student nieznany (konsultant nie ma kartoteki) = pozycja
  zostaje z dopiskiem „jeśli nie jest studentem, pomiń”.
- **Kto zmienia** (O4): Kadry — `team`, head back office
  (`structure.load_division_heads()['back_office']`) — `consultant`, admin —
  obie; każdy z nich widzi obie (`can_edit` w odpowiedzi). Odbiorców ani
  rodzaju ścieżki nie da się zmienić zapisem (422). Pozycji z kluczem nie da
  się usunąć (422) — czytają ją inne moduły (`welcome_mail` — mail powitalny,
  `equipment_kit`, `equipment_issue`).
- **Wersje** (O5): każdy zapis = wersja + 1, nowa pozycja pamięta
  `added_in_version`, sprawa — `template_version`. Nowe sprawy dostają
  bieżącą wersję, trwające zostają na swojej; „Dociągnij do trwających”
  (`POST /templates/{id}/catch-up`) tylko DOPISUJE brakujące pozycje nowszej
  wersji, które pasują do warunków sprawy. Zmiana daty sprawy przelicza ją do
  bieżącej wersji (jak dotąd: terminy otwartych, nowe pozycje, znikają otwarte
  spoza ścieżki).
- **Wejście konsultanta** (`lifecycle_entry.py`): sprawa `audience =
  'consultant'` przy kontrakcie (`contract_id` bez FK, klucz
  `contract:{id}:entry`), bez konta osoby. Zakłada ją hak startu kontraktu
  i przegląd nadchodzących startów (`contract_hooks`, krok `lifecycle` PRZED
  sprawą administracja@); kontrakt ze startem w przeszłości — tylko ręcznie
  („Załóż listę wejścia”). Lista = ścieżka „Konsultant u klienta” + pakiet
  klienta (`client_pack.pack_tasks`: dokumenty, dostępy, odbiór od klienta;
  awaria pakietu nie blokuje wejścia) + pozycje z warunkiem formy. Zestaw
  i wydanie sprzętu są w ścieżce (warunek „sprzęt od nas”), opis zestawu
  z `load_pack(...).equipment_ours`. Wykonawcy: opiekun jedną regułą opieki
  (`care.access.effective_owners`, bez niego head back office), DL —
  rekrutacji, a bez niego główny DL klienta (bez DL — opiekun); zadania
  „osoby” i „przełożonego” odhacza opiekun (O6). Zmiana daty startu kontraktu
  przelicza terminy otwartych zadań; unieważnienie anuluje wejście, trwałe
  usunięcie je kasuje.
- **Jedna lista zamiast trzech**: sprawa „Wejście konsultanta” w Sprawach
  powstaje dalej, ale `lifecycle_case_id` wskazuje wejście, a checklista to
  zadania „Administracja” (odhaczenie w liście → checklista,
  `admin_cases.hooks.sync_entry_checklist`; w drugą stronę
  `sync_entry_tasks_from_checklist`). Zestaw sprzętu to zadanie recepcji
  `contract:{id}:start` z haka Sprzętu: lista pokazuje jego stan (`mirror`),
  odhacza się je tylko w Sprzęcie (409 na liście), bez dzwonka i bez „Moich
  zadań”. Administracja nie dostaje dzwonka (ma kartę sprawy).
- Stare `contract_onboarding_items`: przy włączonym module tylko do odczytu
  (POST/seed/PATCH/DELETE = 409), widoczne pod listą wejścia; wyłączony moduł
  = jak dotąd (zakładka pokazuje starą listę).
- Zakładka „Wejście” kontraktu: `GET /api/hr/lifecycle/contracts/{id}/entry`
  (sekcja Delivery + podgląd Delivery, DL tylko u swoich klientów), lista,
  kroki (przed startem / dzień startu / 2 tygodnie / do 30 dni), „Z czego to
  powstało”, mail powitalny (G2). Prowadzą (dopisanie pozycji, odhaczanie
  każdego zadania): opiekun, DL klienta, head back office, Kadry, admin.
  `complete_task_by_key(db, contract_id=…, key=…, actor_id=…)` z
  `lifecycle_service` odhacza pozycję z kluczem (mail powitalny).
- **Opieka w przekazaniu** (O11): szósty rodzaj pracy `care` — kontrakty
  odchodzącego opiekuna (bez końca i unieważnienia) i domyślne opieki klientów
  przechodzą na przejmującego (ślad `care.owner_set` /
  `care.default_owner_set` z `previous` i `reason: handover`); domyślnie
  przejmuje head back office, bez niego przełożony. DL przejmie opiekę tylko
  z wszystkimi tymi klientami w portfelu (`receiver_out_of_scope`).
- „Koniec projektu konsultanta” jest zasiany, ale sprawy końca projektu
  jeszcze nie powstają (zwrot sprzętu robi hak końca kontraktu jak dotąd).

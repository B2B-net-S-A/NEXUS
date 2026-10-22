# Terminy rozmowy z wklejonego maila klienta (0485, 20.10.2026)
<!-- indeks: „Wklej maila od klienta”, cytat sprawdza kod, mail nie jest zapisywany -->

Zgłoszenie DL-i: przepisywanie terminów od klienta pole po polu (4 terminy ≈ 20
pól daty i godziny) zabiera najwięcej czasu w cyklu rozmowy, a okien typu
„piątek 9–12” nie dało się wpisać. Makiety całego uproszczenia:
https://claude.ai/artifact/6sYkPrefcLsVQjMRb941Eo. Decyzje Artura 20.10.2026:
cztery PR-y po kolei (ten jest pierwszy), wolne/zajęte z kalendarzy przez
aplikację „NEXUS Teams Prep”, wybór rekrutera od razu w kalendarzu (DL tylko
odpisuje klientowi), treści maila nie zapisujemy.

- **Gdzie:** `PasteClientMail` w oknie „Terminy od klienta”
  (`SlotRequestDialog`) i w „Kiedy rozmowa u klienta?” przy ruchu karty
  (`ClientInterviewDateDialog` — przy kilku terminach wybiera się jeden).
  Ręczne wpisywanie zostaje bez zmian; odczyt tylko wypełnia formularz, który
  przy zapisie przechodzi zwykłą walidację (`normalize_slots`).
- **Trasa** `POST /api/interview-cycle/slots/from-mail` — ta sama bramka co
  zapis terminów (`CalendarWriteAccess`), integracja = 403, niczego nie
  zapisuje. Zawsze 200 ze `status`: `ok` | `empty` | `unavailable` (model
  nigdy nie daje 5xx; brak klucza albo błąd = „wpisz je ręcznie”).
- **Model (F32, `interview_slots_from_mail`, Sonnet 5 z Haiku):** dzień,
  godzina i dosłowny cytat dla każdego terminu; daty względne od daty maila
  (pole „Mail z dnia”, domyślnie dziś). **Kontrolę robi kod**
  (`interview_slot_mail.check_parse`, czysta funkcja z testami): termin bez
  cytatu z maila albo z przeszłości odpada; niezgodny dzień tygodnia
  („czwartek 24.10”), weekend i godzina poza 7–20 zostają z ostrzeżeniem
  (ręczna poprawka terminu je zdejmuje); duplikaty łączy, limit 6 jak wniosek
  (`extra_slots`). Koniec zwykłego terminu = start + długość z maila (bez niej
  60 min). Dzień bez godziny („w czwartek rano”) nie staje się terminem — wraca
  w `unclear`.
- **Okno klienta** („między 9 a 12”) wraca z `window: true` i końcem okna;
  wniosek zapisuje je jako termin z `window_end` (PR 2), a godzinę w oknie
  podaje rekruter przy wyborze (`choose(start=…)`, niżej).
- **„Odpowiedź do klienta do”** (`respond_by`) — API przyjmowało je od 0338,
  ale okno go nie wysyłało. Teraz jest polem w oknie i wypełnia się z maila
  („do jutra do 12”; bez godziny = 12:00).
- **Treść maila nie trafia do bazy ani do logu** (log: długość, liczby
  terminów). Pole maila czyści się po udanym odczycie.

Plan pozostałych PR-ów (stan w `TASKS.md` gałęzi): PR 2 — jedno okno
rekrutera: termin + Prep 1 (kalendarz DL) + Prep 2 (swój) z wolnych okien,
okna klienta z wyborem godziny, pominięcie Prepu 2 na zasadach
`rozmowa-bez-prepu-2.md`; PR 3 — wybór rekrutera od razu w kalendarzu, DL
dostaje „Odpisz klientowi” z gotowym tekstem i „Klient zmienił termin”; PR 4 —
„Po rozmowie” z jednym polem tekstu, z którego model rozpisuje pytania,
ofertę, start i stawkę. Żadna istniejąca funkcja cyklu nie znika.

## PR 2 — „Umów rozmowę i prepy” (20.10.2026)

- **Wybór terminu przez rekrutera to jedno okno** (`PickInterviewDialog`,
  `SlotDecisionDialog` w trybie `pick` je otwiera): termin od klienta, w oknie
  klienta godzina („Godzina z kandydatem”, `interview-pick.ts`), opcjonalnie
  „Kiedy kandydat może na prepy? od–do” i godziny obu prepów. „Wybierz termin
  i zaproś na prepy” = `choose` + `POST /preps` dla każdego wybranego prepu
  (planujący za kogoś jest na liście zaproszonych, D3); „Tylko termin” jak
  dawne „Wyślij do DL”; „Zaplanuję później” przy prepie. Nieudany prep nie
  cofa terminu — dymek mówi, który nie powstał.
- **Godziny prepów:** `GET /api/interview-cycle/preps/suggestions` (bramka
  jak `preps/options`), czysta `prep_availability.suggest`: Prep 1 — dzień
  roboczy przed rozmową, potem dwa dni przed, potem rano w dniu rozmowy
  (koniec ≥ 2 h przed); Prep 2 — w dniu rozmowy najbliżej „2 h przed”,
  potem wieczór dnia roboczego przed (koniec ≥ 30 min przed). Godziny pracy
  8–18, z oknem kandydata do 20:00; start ≥ 2 h od teraz; święta jak
  `is_business_day`; Prep 2 omija polecany albo zaplanowany Prep 1.
- **Zajętość** z kalendarzy prowadzących przez aplikację „NEXUS Teams Prep”
  (`prep_availability.busy_blocks`, app-only `getSchedule`, tylko „zajęte /
  wolne”). Sonda na produkcji 20.10.2026 (zgoda Artura): 200, bloki bez
  błędu. Osoba, której kalendarza aplikacja nie czyta, ma „kalendarz
  niedostępny — godziny bez sprawdzenia”; wyłączone prepy w Teams = okno bez
  sekcji prepów. Nic się nie blokuje.
- **Okno klienta w wniosku:** `slots[i].window_end` (normalizacja odrzuca okno
  krótsze niż rozmowa); `choose` z `start` przepisuje termin na wybraną
  godzinę i zapamiętuje `window_start`. Godzina poza oknem albo przy stałym
  terminie = 422.
- Pominięcie Prepu 2 (0482) bez zmian — okno tylko o nim przypomina.

## PR 3 — wybór rekrutera = rozmowa w kalendarzu, DL odpisuje klientowi (0487)

- **`choose` od razu potwierdza** (`interview_slots.confirm`: rozmowa
  `client_interview` w kalendarzu rekrutera, blokada w jego Outlooku jak przy
  potwierdzeniu DL-a) i ustawia `client_reply_pending`. Wyłącznik
  `SLOT_CHOICE_CONFIRMS` (domyślnie włączony; OFF = jak przed 0487).
- **Wyjątek — możliwe przełożenie:** gdy para ma nieodbytą zaplanowaną
  rozmowę (`replaceable_interviews`), wybór czeka na DL-a jak dotąd — okno
  potwierdzenia pyta, czy to przełożenie (reguła 26.09.2026).
- **Zadanie `slots_reply` „Odpisz klientowi”** dla autora wniosku (DL; w
  zakresie „jobs” widzi je też DL rekrutacji), do startu rozmowy; rozmowa
  odwołana w kalendarzu zdejmuje zadanie (audyt 22.10, F33). Okno
  `ClientReplyDialog`: gotowy tekst do skopiowania (`lib/client-reply.ts`,
  imię i nazwisko w mianowniku), „Wysłane klientowi”
  (`POST …/slots/{id}/client-replied`, idempotentne) i „Klient wybrał inny
  termin” (`POST …/slots/{id}/change`: inny termin TEGO wniosku, także godzina
  w oknie; nowa rozmowa, stara odwołana razem z blokadą w Outlooku, rekruter
  dostaje powiadomienie; prepy zostają — prep po rozmowie ekran pokaże jako
  „przełóż”). Obie trasy: role i członkostwo jak potwierdzenie.
- Flaga zamiast „brak daty odpowiedzi”: wnioski potwierdzone przed 0487 mają
  `client_reply_pending = false` i nie stają się zaległymi zadaniami.
  Potwierdzenie przez DL-a (stara ścieżka) od razu odhacza odpowiedź.
- Migracja 0487 stoi po 0486 z PR-a „Zgody” (rozliczenie wydatków) — lustro
  kolumn w `entrypoint.sh`.

## PR 4 — „Co mówił kandydat” w oknie debriefu (0488)

- **Jedno pole na notatkę z telefonu po rozmowie** (`DebriefFromNote` na górze
  `DebriefDialog`, poza trybem tylko do odczytu). „Rozpisz na pola” =
  `POST /api/interview-cycle/debrief/from-text` (bramka jak zapis debriefu,
  integracja = 403, niczego nie zapisuje; zawsze 200 ze `status`).
- **Model F34 `debrief_from_text`** (GPT-6 Luna z zapasem Sonnet 5, jak F25):
  pytania klienta, gotowość do oferty z warunkiem, nowa stawka i start — każdy
  element z cytatem. **Kontrola kodu** (`debrief_from_text.check_parse`):
  element bez cytatu z notatki odpada; kwota stawki tylko, gdy ta liczba stoi
  w notatce (także „16 000”); duplikaty pytań łączone, najwyżej 30.
- **Wypełnia tylko puste pola:** pytania są dopisywane (`mergeQuestions`,
  limit debriefu), oferta i warunek tylko, gdy nie są zaznaczone, stawka tylko,
  gdy „bez zmian”, komentarz kandydata = notatka (+ „Start: …”), gdy pusty.
  „Jak poszło?” zostaje kliknięciem rekrutera. Zapis to zwykły debrief —
  bank pytań klienta, bramka przed „Umową” i powiadomienie DL-a bez zmian.


## Po audycie 21.10.2026 — termin z przeszłości i nazwa przycisku

- **Minionego terminu nie da się wybrać ani potwierdzić.** Terminy wniosku
  sprawdza nie tylko zapis (`normalize_slots`), ale też `choose`, `confirm`
  i `change_confirmed_slot` (`interview_slots._ensure_slot_ahead`): start
  wcześniejszy niż teraz − 5 min = 422 „Ten termin już minął — wybierz
  przyszły.”. Od 0487 wybór od razu zakłada rozmowę i blokadę w Outlooku —
  bez tej kontroli dzień później w kalendarzu stawała „zaplanowana” rozmowa
  w przeszłości. Okna `PickInterviewDialog` i `ClientReplyDialog` wyłączają
  takie terminy z dopiskiem „termin minął” (`interview-pick.slotPassed`, ta
  sama tolerancja; okno klienta mija, gdy nie zmieści się w nim rozmowa).
- **Przycisk mówi, co robi:** bez prepów do zaproszenia główny przycisk
  `PickInterviewDialog` to „Wpisz do kalendarza” (jak dymek „Rozmowa jest
  w kalendarzu…”), nie „Wyślij do DL”. Nie wracaj do starej nazwy.

## „Inna godzina…” przy prepie (22.10.2026)

- **Rekruter może wpisać prep spoza podpowiedzi.** W `PickInterviewDialog`
  przy obu prepach, obok trzech podpowiedzi, jest „Inna godzina…”: dzień
  (dni robocze od dziś do dnia rozmowy) i godzina co 15 min, pasek dnia
  prowadzącego z jego zajętością i komunikat pod spodem (`interview-pick.
  checkManualPrep`). Pojawia się też wtedy, gdy podpowiedzi brak — do tej
  daty jedynym wyjściem było „Zaplanuję później” i okno z panelu osoby bez
  kalendarza.
- **Blokada** (główny przycisk czeka, „Tylko termin” działa): prep kończy się
  po starcie rozmowy, nachodzi na drugi prep tej osoby (Prep 1 ma
  pierwszeństwo), godzina minęła. **Ostrzeżenie** (zapis wolno): prowadzący
  ma wtedy zajęte (z „Najbliżej wolne tego dnia”), zapas przed rozmową
  mniejszy niż 2 h (Prep 1) / 30 min (Prep 2), poza 8–18, mniej niż 2 h od
  teraz. Kalendarz niewidoczny = „nie sprawdzimy, czy ma wtedy wolne”.
- **Zajęte u prowadzącego to ostrzeżenie, nie blokada** (decyzja Artura):
  zajęte bywa przesuwalnym blokiem, a blokada wypychała do okna bez
  kalendarza. Prowadzący dostaje w dzwonku „Nachodzi na inne spotkanie
  w Twoim kalendarzu (…)”.
- **Serwer sprawdza kalendarz przy każdym zapisie prepu** (`POST /preps`,
  `prep_availability.busy_overlap`), także dla podpowiedzi: między otwarciem
  okna a kliknięciem nikt nie rezerwuje godziny. Kolizja bez `accept_busy`
  = 409 `PREP_SLOT_BUSY` z przedziałem w `message`; okno z panelu osoby
  pokazuje wtedy „Zapisz mimo to”. Kalendarz nieznany (spoza grupy, błąd
  Grapha) niczego nie blokuje. Blok o tym samym początku i końcu co prep
  (±1 min) się nie liczy — to sierota z poprzedniej próby z tym samym
  `client_request_id`. Prep tego prowadzącego zapisany w NEXUSIE liczy się
  zawsze, także w identycznym przedziale (`organizer_prep_spans`; audyt
  22.10, F32: dwóch rekruterów o tę samą podpowiedź dla różnych kandydatów). „Zapisz mimo to” znika po zmianie terminu, długości
  albo prowadzącego. Zmiana terminu (`PATCH`) bez tej kontroli.
- **`suggestions` niesie `busy`** — zajęte bloki prowadzącego od teraz do
  rozmowy (tylko „zajęte/wolne”, bez tytułów; to samo `getSchedule`, bez
  dodatkowego zapytania). Wpływ na sloty: prep ręczny zajmuje 45 min w
  Outlooku prowadzącego jak podpowiedziany i kolejne podpowiedzi go omijają.

# Terminy rozmowy z wklejonego maila klienta (0485, 20.10.2026)
<!-- indeks: „Wklej maila od klienta”, F32 Sonnet 5, cytat sprawdza kod, treść maila nie jest zapisywana, plan 4 PR-ów uproszczenia cyklu -->

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


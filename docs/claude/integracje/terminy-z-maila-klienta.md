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
- **Okno klienta** („między 9 a 12”) wraca z `window: true` i końcem okna. Do
  PR 2 wniosek zapisuje je jako termin od początku okna, a notatka dla
  rekrutera mówi „Okno klienta: … — godzinę ustal z kandydatem”. Wybór godziny
  w oknie przez rekrutera dochodzi w PR 2.
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

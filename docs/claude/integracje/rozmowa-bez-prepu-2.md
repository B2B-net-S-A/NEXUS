# Rozmowa u klienta bez Prepu 2 — wyjątek, nie wybór (0480, 20.10.2026)

Zgłoszenie rekrutera: zdarza się, że kandydat nie znajdzie czasu na drugi
prep przed rozmową u klienta. Artur obawiał się, że zwykłe „Prep 2
opcjonalny” skończy się na „nigdy nie ma czasu”. Decyzja (makiety
https://claude.ai/artifact/5m626Yzju2zgioy3ECDETw): pominięcie to wyjątek
z warunkami, a telefon do kandydata przed rozmową jest obowiązkowy.

- **Kiedy wolno** — jedna reguła `interview_cycle.prep2_skip_status` (ekran,
  dok osoby i serwer liczą na tej samej migawce pary). Rozmowa rundy prepów
  jest dziś albo w najbliższy dzień roboczy (`is_business_day`, polskie
  święta; piątek → poniedziałek się liczy), Prep 1 już się odbył i nie jest
  „słaby” ani „bez nagrania” (czekający na transkrypt jest OK), Prepu 2 nie
  ma w kalendarzu. Odmowy: `too_early`, `prep1_missing`, `prep1_weak` → 422
  z `detail.code = PREP2_SKIP_<STATUS>`, drugi zapis → 409. Przy rozmowie
  dalej nie ma przycisku, tylko zdanie „jest czas na Prep 2”.
- **Zapis** `POST /api/interview-cycle/prep2-skip`: bramki `POST /preps`
  (sekcja Pipeline, zapis kalendarza, członkostwo w rekrutacji) i do tego
  ludzie pary (`prep2_skips.ensure_skip_editor`): rekruter kandydata,
  prowadzący rozmowę, DL rekrutacji, ich zastępcy, HoR i admin — inaczej
  zapisywały Finanse i rekruter spoza rekrutacji. To samo przy odhaczeniu
  telefonu. Powód z listy (`no_slot`, `short_notice`, `prep1_covered`,
  `other` — „inny” wymaga opisu) i `call_at` — telefon do kandydata przed
  rozmową (do 2 h wstecz, zawsze przed startem rozmowy). Tabela
  `prep2_skips`, jeden wpis na rozmowę (`interview_event_id` UNIQUE),
  lustro DDL w `entrypoint.sh`.
- **Ślad:** krok Prep 2 „pominięte” (przekreślony, szary) z powodem
  i autorem — nigdy jak zrobiony; zadanie `precall_due` „Telefon przed
  rozmową” zamiast `prep2_missing` (pilne, gdy godzina minęła), odhaczane
  `POST …/prep2-skip/{id}/call-done` z notatką; plakietka Tablicy
  `prep2_skipped` („Bez Prepu 2 · telefon dziś 18:00”) zamiast „Brak prepu”;
  kolejka `prep_attention` nie liczy go jako brak. Dzwonek
  `prep2_skipped` do Delivery Leada rekrutacji (licznik, bez dymka; autor-DL
  nie dostaje).
- **Hamulec = pomiar, nie blokada.** Raport „Jakość prepów” ma tabelę
  „Rozmowy bez Prepu 2 · ostatnie 30 dni” per właściciel rozmowy
  (rekruter): z powodem, „pominięte bez słowa” (rozmowa się odbyła, prepów
  < 2, bez wpisu) i powody. Próg: > 20% rozmów i co najmniej 2 — wiersz
  na pomarańczowo, a przy zapisie pominięcia każdy HoR dostaje
  `prep2_skip_threshold` raz na 30 dni na osobę (bez pętli w tle). Zgody DL
  przed pominięciem świadomie nie ma: przy rozmowie jutro rano przyszłaby
  za późno.
- Prep 2 założony po zapisie (`POST /preps`, `prep_no=2`) kasuje
  pominięcie przed przyszłą rozmową (`prep2_skips.clear_upcoming`) — inaczej
  raport liczyłby rozmowę jako „bez Prepu 2”.
- Rozmowa, która minęła bez Prepu 2 i bez wpisu, nadal ma krok „pominięte”,
  ale z dopiskiem „bez zapisanego powodu”.

# „Ostatnio z osobą” pod wierszem listy i „Szuka aktywnie” zmieniane kliknięciem (18.11.2026)
<!-- indeks: linia pod wierszem zamiast kolumny „Ostatnie odrzucenie”, dwie informacje najnowsza pierwsza, bez wnioskowania z treści, pigułka statusu z uprawnieniem okna „Dostępność” -->

Decyzja Artura z 18.11.2026 (makiety: https://claude.ai/artifact/Lk3LqawjifGhmJwn59Wrg3).
Zgłoszenie rekrutera: przy osobie było „Szuka aktywnie”, a obok cytat „nie jest
zainteresowany, nie wydzwaniać”. Cytat był z 30.07 (kolumna „Ostatnie
odrzucenie”, data ucięta), a 02.11 była rozmowa z „Dostępność: ASAP”, z której
automat wpisał status. Rekruter nie miał jak tego odczytać ani gdzie zmienić
statusu bez trzech kliknięć.

## Co widzi rekruter

- **Linia „Ostatnio z osobą”** pod każdym wierszem listy kandydatów (też
  w „Szukaj ręcznie”): dwie ostatnie informacje o osobie — rozmowa, notatka
  albo odrzucenie — najnowsza pierwsza, każda z datą w kalendarzu firmy.
  Pełna szerokość, bo w wąskiej kolumnie zdanie ucinało się po kilku słowach.
  Wiersz ma stałe +28 px (`RECENT_FACTS_LINE_HEIGHT`, wirtualizacja liczy
  wysokość co do piksela). Brak danych = „brak notatek i odrzuceń”, brak pola
  w odpowiedzi = „—”.
- **Kolumny „Ostatnie odrzucenie” nie ma.** Filtr „Odrzucenie” i pasek nad
  tabelą zostają (`ostatnie-odrzucenie-kolumna-filtr-pasek.md`). Id
  `last_rejection` w zapisanych wyborach kolumn jest ignorowane. Razem z
  kolumną zniknął mechanizm „domyślnie tylko na szerokim ekranie”
  (`wideDefault`, `addedAfterSavedPrefs`) — nie miał innych kolumn.
- **„Szuka aktywnie” klikalne** na liście i w profilu
  (`components/v2/candidates/AvailabilityStatusPicker.tsx`): cztery wybory,
  zapis od razu `PATCH /api/candidates/{id}`. Osoba bez statusu ma
  „+ Czy szuka?”. Uprawnienie jak w oknie „Dostępność”:
  `candidate.profile_fact.manage` i `candidate.write`; bez nich zostaje sama
  pigułka (bez zachęty do kliknięcia, które skończyłoby się 403).

## Czego nie robimy (i dlaczego)

- **Nie wnioskujemy z treści.** Pomiar na kopii produkcji 18.11: 113 osób ma
  „Szuka aktywnie” z automatu i nowszą notatkę z „nie jest zainteresowany”,
  ale część to odmowa jednej oferty („nie jest zainteresowany Nordeą”,
  „…tymi technologiami”). Automat tego nie odróżni, więc linia pokazuje
  kolejność faktów, a status zmienia człowiek. Nie dodawaj „sprzeczne /
  sprawdź” ani automatu ustawiającego „Nie szuka” bez nowej decyzji.
- Nocny odczyt notatek (`notes_profile_fill`) dalej zmienia tylko „Nie
  ustalono” na „Szuka aktywnie” — wybór człowieka zostaje.

## Definicja (jedno miejsce: `app/services/candidate_recent_facts.py`)

- Notatki z zakładki „Rozmowy” (`note_kinds.talks_clause`) z widocznością
  stawki do klienta jak „Ostatnia notatka” (`note_rate_visibility_clause`),
  bez odpowiedzi w wątku i usuniętych u źródła. Karta z rozmowy i fakty ze
  screeningu = „rozmowa” ze skrótem „dostępność X, N zł/h”; reszta =
  „notatka” z treścią (160 znaków).
- Ostatnie odrzucenie z `candidate_last_rejection.page_rows`, z klientem.
  Import Traffita zapisywał ten sam opis w notatce statusu i przy odrzuceniu —
  ten sam dzień i ten sam tekst pokazujemy raz.
- `GET /api/candidates?include_recent_facts=true` → `recent_facts` w wierszu;
  dwa zapytania na stronę. Flaga jest na listach pomijanych przy zapisie
  wyszukiwania (front, `saved_search_payload`, `saved_search_alerts`).
- Front: `lib/candidate-recent-facts.ts` (daty, etykiety, cudzysłów dla cudzych
  słów), `components/v2/candidates/RecentFactsLine.tsx`.

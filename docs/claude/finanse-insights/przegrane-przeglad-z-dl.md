# Insights → „Przegrane”: przegląd przegranych rekrutacji z Delivery Leadami (25.11.2026)
<!-- indeks: zakładka `przegrane`, `services/lost_review.py`, `api/insights_lost_review.py`, 0783, `job_loss_reviews`, `lost_review_lessons`, „Co zdecydowało?” w oknie zamknięcia, „Skąd wiesz?”, R3 pytanie do HM i dzwonek po 3 dniach roboczych, F56 `lost_review_summary`, zasady klienta, `ClientLessonsStrip` -->

Decyzje Artura z 25.11.2026 („rób wszystko R1, R2 i R3”, „osobny moduł
w Insights”, „jeden PR”). Makiety i dane:
https://claude.ai/artifact/H3BNSMHGbmc33Uwuy7PK4K. Co miesiąc HoR i DL omawiają
przegrane, a NEXUS nie wiedział, dlaczego przegrywamy: na kopii z 25.11 od 12.10
w przegranych poszło 505 CV, 324 z nich zamknął automat jako „Klient wybrał kogoś
innego”, reakcję klienta miało 21%, a notatkę przy „Wybrali konkurencję” 23 z 78
zamknięć (głównie wklejony mail CPro). Szybkość i liczba CV nie różniły wygranych
od przegranych; różniło je przejście z CV do rozmowy (83% vs 37% w listopadzie).

## Zakładka (R1)

- **Miejsce i dostęp:** zakładka „Przegrane” przed „Wnioskami”, widzą admin, Head
  of Recruitment i Delivery Lead (`VIEWER_ROLES`, lustro `LOST_REVIEW_ROLES`
  w `lib/insights-roles.ts`). DL widzi całą firmę, bo spotkanie jest wspólne.
- **Okres:** `PeriodPicker`, domyślnie bieżący miesiąc. Okno nie sięga przed
  12.10.2026 (`competition_history.cutover_utc`) — wcześniej zamknięcia nie miały
  powodów. Trend: do 6 miesięcy do końca okresu.
- **Wygrana / przegrana jak w hit ratio** (`hit_ratio_closures.closure_group`):
  przegrana = `competitor` albo `no_activity` bez zatrudnienia. „Do przejrzenia”
  i „Nie liczy się” są poza modułem — od nich jest raport „Zamknięcia i hit ratio”.
- **Etap przegranej** = najdalszy etap, do którego doszła nasza osoba
  (`analytics_first_milestones`): bez CV, CV bez rozmowy, po rozmowie, po akceptacji.
- **Ocena klienta** = odrzucenie „Odrzuca klient” z powodem innym niż
  `client_chose_other` / `request_closed` — te nadaje zamknięcie rekrutacji, nie klient.
- **Wnioski z liczb** liczy kod (`lost_review.findings`), są zawsze, także bez
  modelu. Nowa reguła wniosku = funkcja tam i test.
- **Bez cache** odczytu: wybór „Dlaczego?” i wnioski widać od razu.

## „Co zdecydowało?” (R2) i zapis na spotkaniu

- Sześć powodów (`WHY`, lustro `LOST_WHY`), do dwóch, i „Skąd wiesz?”
  (`client` / `ours` / `unknown`). Oba opcjonalne.
- **Okno zamknięcia** pyta tylko przy „Przegraliśmy” (`competitor`). Pola idą
  w `POST /close` i `PATCH /close-reason` (`lost_why`, `lost_why_source`) i tylko
  wtedy, gdy coś wybrano — puste okno nie nadpisuje zapisu ze spotkania. Przy innym
  powodzie serwer odmawia 422 `lost_why_not_lost`.
- **Wiersz należy do jednego zamknięcia:** `job_loss_reviews.closed_at` =
  `jobs.closed_at` z chwili zapisu. Po „Otwórz ponownie” i nowym zamknięciu stary
  wybór przestaje się liczyć bez kasowania.
- **Zapisy ze spotkania** (`PUT …/why`, wnioski) mają bramkę sekcji Rekrutacja,
  nie Insights: DL ma w Insights tylko odczyt, a zapis „Dlaczego?” to praca na
  rekrutacji jak okno zamknięcia. `POST …/ai-summary` jest w
  `READ_ONLY_POST_ROUTE_TEMPLATES` (nic nie zapisuje).

## Wnioski ze spotkania = zasady klienta

- „Co zmieniamy?” przy rekrutacji: dla tej rekrutacji, klienta albo wszystkich
  (`lost_review_lessons`). „Zdejmij” ustawia `archived_at`, wiersz zostaje.
- **Zasada klienta** widać w tabeli klientów z wynikiem „czy pomogło”: wygrane
  i przegrane klienta od 12.10 przed datą zasady i po niej; przy mniej niż 3
  zamknięciach po zasadzie ekran pisze, że za wcześnie.
- **Pasek na stronie otwartej rekrutacji** (`ClientLessonsStrip`): zasady klienta
  i „wszyscy klienci”, jedna linia, tylko dla ról modułu. Bez zasad i przy błędzie
  odczytu pasek się nie pokazuje — to podpowiedź, nie dane rekrutacji.

## Pytanie do klienta (R3)

- „Nie wiemy — zapytam klienta” → po 3 dniach roboczych dzwonek do DL rekrutacji
  (bez DL: do osoby, która zapisała) typu `request_review_needed` (zadanie, bez
  maila), raz na zamknięcie (`ask_reminded_at`). Biegnie w pętli `job_idle`
  (`run_ask_reminders_safely`, własna sesja), więc w oknie 8–17 dnia roboczego.
  Zmiana źródła na inne i z powrotem zaczyna liczenie od nowa.
- Szkic pytania do HM (`client_question`) bez nazwisk kandydatów; DL kopiuje go
  i wysyła ze swojej skrzynki. NEXUS niczego nie wysyła do klienta.

## Rady AI (F56 `lost_review_summary`)

- Model z rejestru (`ai_models`, Sonnet 5.5 z zapasem Sonnet 5), wywołanie
  w `ai_feature()`. Wejście (`model_input`): liczby, etapy, powody z list, nazwy
  klientów i teksty zasad — **bez nazwisk DL i kandydatów, notatek, maili
  i stawek**. Strażnik: `test_model_input_has_no_people_or_notes`.
- `check_summary` przyjmuje tylko znane pola; rada dla klienta spoza danych idzie
  do „wszyscy”. Ten sam okres i te same dane = odpowiedź z cache przez dobę.
- Wynik modelu to dodatek: błąd daje 422 `lost_review_ai_failed` z komunikatem,
  a liczby i wnioski z reguł zostają na ekranie.

## Schemat

Migracja 0783 (`lost_review_schema.py` — to samo źródło czyta `entrypoint.sh`),
sonda w `/api/health/deep`, wartość enuma `aifeaturekey` z seedem `ai_features`.
Testy: `backend/tests/test_lost_review.py`, front: `PrzegraneView.test.tsx`,
`JobCloseWithReasonDialog.test.tsx`, `ClientLessonsStrip.test.tsx`.

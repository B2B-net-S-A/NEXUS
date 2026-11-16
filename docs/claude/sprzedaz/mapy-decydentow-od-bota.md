# Mapy decydentów od bota (rodzaj `people`) — decyzja Artura 12.11.2026
<!-- indeks: Grok Bot buduje mapy decyzyjne, osoby i kontakty tylko ze źródeł publicznych, link i data przy osobie, e-mail i telefon tylko z własnym źródłem, bez zgadywania wzorców, bez LinkedIna, bez logowania, sales_bot_results kind people, przegląd jak lista z researchu, „Znajdź decydentów (bot)”, raz na firmę na dobę, tygodniowy przegląd map poniżej 3 osób, plakietka „Osoby od bota”, pochodzenie „Grok Bot”, source_published_at, dane osobowe od bota do USA -->

Artur 12.11.2026 zdecydował, że bot researchu buduje pełne mapy decydentów firm
sprzedaży, z danymi kontaktowymi. NEXUS dalej wysyła botowi tylko nazwę i domenę
firmy (`sygnaly-grok-bot.md`); bot może osoby ODESŁAĆ. Rodzaj `people` korzysta
z fundamentu zadań bota (0684, sekcja „Zadania bota” w `sygnaly-grok-bot.md`)
i z maszyny importu listy z researchu (`fabryki-it-import-listy-z-researchu.md`).
Bez migracji.

Kod: `backend/app/services/sales/bot_tasks/people.py` (polecenie, model raportu,
zapis wyników, przegląd i przyjęcie), cele tygodniowe
`services/sales/signal_targets.py` (`people_company_ids`), krok pętli
`tasks/sales_signals.py`, trasy `backend/app/api/sales_bot_people.py`
(`/api/sales/bot-people`), front `frontend/src/components/sales/bot-people/`,
klient API `lib/api/sales-bot-people.ts`.

## Zasady źródeł (polecenie i model raportu)

- **Tylko osoby wymienione z imienia i nazwiska na publicznych źródłach, które bot
  sam otworzył:** strona firmy, komunikaty prasowe, agendy konferencji, publiczne
  wywiady, publiczne rejestry. Przy każdej osobie link (`source_url`, tylko http(s))
  i data publikacji (`published`; data z przyszłości jest czyszczona).
- **E-mail i telefon tylko, gdy są wydrukowane na publicznym źródle,** każdy
  z własnym linkiem (`email_source_url`, `phone_source_url`). Bot nigdy nie zgaduje
  adresów z wzorców i nie wymyśla numerów. Model raportu to wymusza: kontakt bez
  własnego źródła albo w złym kształcie (te same walidatory co plik:
  `research_file.valid_email`, `valid_phone`, `valid_link`) odpada z ostrzeżeniem
  przy osobie, a osoba zostaje. Przegląd pokazuje to ostrzeżenie.
- **Bez LinkedIna:** bot nie zbiera z niego danych. `linkedin_url` tylko jako link
  do profilu (`linkedin.com`), który był na otwartej stronie; inny adres odpada.
- **Bot nigdzie się nie loguje.** Nie dokładaj do polecenia, kodu ani dokumentacji
  instrukcji logowania do żadnej usługi zewnętrznej.
- Najwyżej 15 osób na firmę, `extra="forbid"` (pola spoza formatu to 422), obszar
  (`area`) z listy, `level_hint` 1–3 jak poziomy importu (zarząd i VP, Head
  i Director, reszta). Bez podpowiedzi poziom bierze się z nazwy stanowiska
  (`research_file.level_from_title`).

## Wyniki do decyzji

- **Jeden wiersz `sales_bot_results` na firmę** z listą osób (`payload.people`,
  wiersze numerowane od 1) i stanem zapisu per wiersz (`payload.outcomes`).
- **Osoba trafia do wyników raz na firmę.** Odpada osoba już na mapie konta
  w Fabrykach IT i osoba z poprzedniego wyniku tej firmy, także odrzuconego
  (to samo imię i nazwisko bez względu na kolejność wyrazów albo ten sam e-mail).
  Tygodniowy bieg nie podsuwa więc tych samych ludzi po decyzji handlowca.
  Firma bez nowych osób nie dostaje wiersza.
- Odpowiedź dla bota i logi to same liczby (`numbers_only`).
- **Osoby, które odeszły** (13.11.2026): lista `left` przy firmie (imię i nazwisko,
  dawne stanowisko, `source_url`, `published` wymagane, `left_on` gdy źródło podaje,
  `extra="forbid"`). Znane osoby, także te odrzucone wyżej jako powtórka, idą do
  zakładki Kontakty z nowszym stanowiskiem albo stanem „nie pracuje”
  (`kontakty-jedna-lista.md`).

## Zapis od razu (decyzja Artura 13.11.2026)

Osoby z raportu trafiają na mapę od razu (`people.add_now` w `_ingest`), tą samą
ścieżką co przegląd (`apply` → `research_import.accept`), z pewnością `confirmed`
i bez decyzji handlowca (`decided_by_user_id` puste). Autor zapisu: osoba, która
uruchomiła bieg, inaczej opiekun karty; opiekun karty zostaje opiekunem nowego
konta. Przegląd niżej zostaje tylko dla wyników, których nie da się zapisać bez
człowieka: marka z kilkoma kartami (`CHOOSE`) i karta bez opiekuna przy biegu
z pętli. Odpowiedź dla bota ma liczby `added` i `waiting`. Ślad: historia karty
(`sygnaly-grok-bot.md`, „Zapis od razu”).

## Przegląd i zapis (jak lista z researchu)

- **Leady → „Lista z researchu” → „Osoby od bota”** (konto z „Sprzedaż: edycja”):
  lista wyników do przeglądu, „Przejrzyj” otwiera ten sam ekran co plik
  (`ResearchReview`): stany firmy, „Już na mapie”, poziom, ostrzeżenia
  i „Znamy teraz”. Wiersz to osoba z wyniku zamieniona w `ResearchRow`
  (`people.to_rows`), pewność `confirmed` (do 13.11.2026 „do weryfikacji”).
- **Cel to karta firmy, o którą pytano bota** (`people.pin`), regułami importu:
  klient NEXUSA i nasza firma zostają odmową, „Nie kontaktować” blokuje, a gdy inna
  karta tej marki ma konto w lejku, kartę wskazuje człowiek. Karta bez konta dostaje
  konto w lejku Fabryki IT przy pierwszej akceptacji, jak przy pliku.
- **Zapis wysyła tylko numer wiersza, poziom i kartę** (`POST /{id}/people`).
  Treść osoby i kontakty serwer bierze z wyniku, więc ekran nie dołoży kontaktu
  bez źródła. Zapis idzie przez `research_import.accept`: `DecisionPersonCreate`,
  punkt zapisu na wiersz, blokada akceptacji, osoba bez dubla.
- **Pochodzenie na mapie:** `source_label` „Grok Bot”, `source_url` (strona, na
  której bot znalazł osobę), `source_published_at` (data publikacji),
  `source_added_at` (dzień zapisu). Linia źródła w oknie osoby i kolejce pokazuje
  datę publikacji.
- **Stan wyniku:** po zapisie `partial`, gdy część osób czeka, `accepted`, gdy każda
  ma wynik zamykający (dodana, już na mapie, odmowa firmy). Błąd wiersza nie zamyka
  go. „Odrzuć resztę” to wspólne odrzucenie wyniku (`/bot-results/{id}/reject`);
  dodane osoby zostają na mapie. `POST /bot-results/{id}/accept` (hak rodzaju)
  dodaje wszystkie otwarte osoby na ustaloną kartę, a przy wyborze karty odmawia 409.

## Uruchomienie

- **„Znajdź decydentów (bot)”** na mapie decyzyjnej konta w lejku Fabryki IT i na
  karcie firmy, dla „Sprzedaż: edycja” (`POST /companies/{id}/start`, 10/min).
  Jeden bieg na firmę na 24 godziny (nieudany start webhooka się nie liczy)
  i żadnego, gdy wynik tej firmy czeka na przegląd; odmowa także dla klienta
  NEXUSA, „Nie kontaktować” i naszej firmy. Bieg z przycisku ma
  `requested_by_user_id`.
- **Tygodniowo w poniedziałek od 8:00** (pętla `sales_signals`, więc też tylko
  przy `SALES_SIGNALS_ENABLED`): konta otwarte w lejku Fabryki IT z mapą poniżej
  3 osób, najuboższe mapy najpierw, najwyżej 20 firm. Bez klienta NEXUSA,
  „Nie kontaktować”, naszej firmy, firm z wynikiem do przeglądu i z biegiem
  `people` z ostatnich 7 dni.
- **Plakietka „Osoby od bota”** na wierszu listy kont i przy mapie, z odnośnikiem
  do przeglądu (`/sales/leads?osoby=<id>`).
- Wszystko za flagą `SALES_BOT_TASKS_ENABLED`; wyłączona: lista mówi
  `enabled: false`, przyciski i plakietki znikają, trasy przeglądu, zapisu i startu
  odpowiadają 409. Przed pokazaniem ludziom próba skryptem
  `python -m scripts.sales_signals_run --kind people --company-ids <id>`
  (`docs/sales-grok-bot-setup.md`, sekcja 4).

## Dane osobowe

- **Od 12.11.2026 dane osobowe przychodzą od bota:** imiona, nazwiska, stanowiska
  i kontakty ze źródeł publicznych przetwarza bot na komputerach w USA. Artur
  przyjął przekazanie do USA. Do bota dalej nie idą żadne osoby z NEXUSA.
- Reguła z 09.11.2026 (`sygnaly-grok-bot.md`, „Pilot i warunek rozszerzenia”)
  zaleca opinię IOD przy szerszym użyciu danych; budowa map osób przez bota jest
  takim użyciem.
- Na ekranach nie ma tekstów RODO ani ostrzeżeń prawnych (decyzja z 10.11.2026,
  `fabryki-it-import-listy-z-researchu.md`).

Testy: `backend/tests/test_sales_bot_people_unit.py`,
`backend/tests/test_sales_bot_people_api.py`,
`frontend/src/components/sales/__tests__/sales-bot-people.test.tsx`, wzorzec
`tests/data/authz_golden/sales_bot_people.json`.

## Mapa firmy z Cognism

Karta firmy ma zakładkę „Mapa decydentów” dla użytkowników z prawem edycji
Sprzedaży. Pokazuje aktualne stanowisko, służbowy e-mail i numer bezpośredni
albo komórkowy, jeśli Cognism je udostępnił. Przy osobie widać źródło oraz
osobne daty sprawdzenia stanowiska i dostępnych kontaktów. Bot otwiera pełne
profile osób w panelu Cognism i odsyła wyniki osobnym webhookiem.
NEXUS zapisuje jednoznaczne dopasowania po sprawdzeniu pracodawcy i sprzeciwów.
Brak pola w nowym odczycie nie usuwa wcześniejszej wartości.
Od 13.11.2026 osoby z mapy trafiają też do zakładki Kontakty, a osoba
z `active = false` zostaje na mapie jako „Nieaktywna rola” zamiast znikać
(reguły: `kontakty-jedna-lista.md`).

Mapa należy do karty firmy. Nowe firmy zakwalifikowane przez zakończony
research trafiają do kolejki Cognism. Przycisk na karcie pozwala zlecić
uzupełnienie mapy. Konfiguracja i próba są w instrukcji
`docs/sales-grok-bot-setup.md`.

# Ogłoszenie gotowe zaraz po „Utwórz” — krok „Ogłoszenie” (23.11.2026)
<!-- indeks: `job_ad/on_create.py`, `prepare_after_create` po commicie, `material.ad_lang` (EN z „English”), `recent_channels` w odpowiedzi okna, `?ogloszenie=nowa`, `AfterCreatePublish`, widełki raz dla JJIT i Pracuj.pl, „Opublikuj w N miejscach”, „Później” -->

Decyzja Artura z 23.11.2026 (wariant 1 „Porządki”, makiety
https://claude.ai/artifact/5CT33qwDPP5vurc1CVY7yV, para „Ogłoszenie”), po
zgłoszeniu Igora, że założenie rekrutacji trwa długo. Pomiar z kopii produkcji
z 23.11.2026: treść ogłoszenia (`job_ads`) powstawała dopiero w pętli nocnej albo
po ręcznym „Przygotuj”, a publikacja na portalu miała medianę 23 h po utworzeniu
rekrutacji (789217: JustJoin.IT +3 dni, Pracuj.pl +6 dni; 96 ze 137 publikacji
zrobił DL). Stawkę do maila Pracuj.pl DL wpisywał drugi raz, osobno od widełek
JustJoin.IT.

Kod: `services/job_ad/on_create.py`, `prepare.prepare_one(on_create=True)`,
`material.ad_lang`, wpięcie w `job_lifecycle.apply_job_create`; front
`components/v2/job-ad/AfterCreatePublish.tsx`, tryb `afterCreate`
w `JobAdWindow`, `newJobAdHref` w `lib/job-ad-mail-intent.ts`, przejście
w `NewJobPage` po utworzeniu.

## Treść przy tworzeniu

- **Efekt po commicie, nic w transakcji tworzenia.** `apply_job_create` dodaje
  `effects.later(prepare_after_create, …)`: zadanie w tle żądania (ekran i API v1),
  własna sesja, `INSERT … ON CONFLICT DO NOTHING` jak noc. Odpowiedź `POST /api/jobs`
  na model nie czeka.
- **Wynik modelu jest dodatkiem.** Model z rejestru (`job_description_generator`,
  `generate._ask_model` w `ai_feature()`). Brak klucza, błąd albo pusta odpowiedź =
  nic się nie zapisuje — zostaje dzisiejsza droga: pętla nocna i „Przygotuj
  ogłoszenie” w oknie. Złożenia z pól (`template`) przy tworzeniu NIE zapisujemy,
  bo wtedy noc i okno już by go nie poprawiły modelem. Każdy wyjątek ląduje w logu,
  tworzenie zostaje 201.
- **Język:** `material.ad_lang` — „Język pracy” ze słowem „English” i bez „polski /
  Polish / PL” = ogłoszenie po angielsku; reszta po polsku. Na kopii z 23.11.2026
  tak zapisują pole requesty Nordei i innych banków międzynarodowych („Fluent in
  English”, „English C1”), a „angielski B2” to wymóg w polskiej rekrutacji. DL
  zmienia język przełącznikiem PL/EN w oknie („Przygotuj ponownie”).
- `generated_by` puste = przygotował NEXUS (jak noc); w `ai_operations` wywołanie
  ma autora tworzenia (konto serwisowe API v1 = bez osoby).

## Krok „Ogłoszenie” (`/jobs/{id}?ogloszenie=nowa`)

- `/jobs/new` po utworzeniu przechodzi na `newJobAdHref(id)` zamiast toastu
  „Wyślij ogłoszenie na Pracuj.pl” na 15 s. Ścieżka z sekcją „Ogłoszenie na
  portalach” (`NewJobPortalsStep`, `job_postings`) zostaje bez zmian — to druga,
  starsza droga opisu i nie łączymy jej z tym krokiem.
- Okno „Ogłoszenie” w trybie „po utworzeniu”: pasek „Rekrutacja utworzona…
  Ostatni krok: ogłoszenie. Krok 2 z 2”, treść po lewej jak zawsze (poprawki
  w zakładkach), po prawej `AfterCreatePublish` („Gdzie publikujemy”) zamiast
  kolumny kanałów. Do czasu treści okno pyta serwer co 3 s
  (`AFTER_CREATE_WAIT_MS` = 90 s) i nie pokazuje „Przygotuj ogłoszenie”, żeby
  DL nie zamówił drugiej treści; po 90 s wraca zwykły pusty stan.
- **Kanały zaznaczone jak w ostatnich rekrutacjach klienta**
  (`recent_channels` w `GET …/portal-ad`): z 5 ostatnich rekrutacji klienta,
  które miały jakiekolwiek ogłoszenie (strona kariery = zatwierdzony opis,
  JustJoin.IT i Pracuj.pl = wiersz `job_ad_publications` także zdjęty, Pracuj.pl
  też mail do opiekuna), kanał użyty w co najmniej połowie. Klient bez historii =
  wszystkie. Zaznaczone są tylko kanały, które da się teraz opublikować; portale
  tylko dla DL rekrutacji, Head of Recruitment i admina (jak karty kanałów).
- **Widełki dla kandydata wpisuje się raz** i idą do JustJoin.IT (`salary`)
  i do maila Pracuj.pl (`rate_from` / `rate_to`). Nadal nigdy z budżetu
  rekrutacji ani stawki Championa (`widelki-w-ogloszeniu-albo-powod.md`). Bez
  widełek JustJoin.IT pyta o powód przez `useConfirmV2().askReason`, a mail
  Pracuj.pl, który wymaga stawki, czeka na „Dokończ”.
- **„Opublikuj w N miejscach”** woła te same trasy co karty — strona kariery
  (`POST …/career`), JustJoin.IT (`POST …/jjit`, ustawienia z
  `portal-listing-defaults` + kategoria z ostatniej publikacji w tej samej
  kategorii kompetencji), mail do opiekuna (`POST …/pracuj-mail`). Każdy kanał
  osobno: odmowa jednego nie zatrzymuje reszty. Brak kategorii, odmowa ustawień
  przez portal albo brak skrzynki M365 (412) = „Dokończ” otwiera okno kanału
  z wpisanymi widełkami. W trybie linku JustJoin.IT strona kariery jest
  zaznaczana razem z nim.
- **„Później”** zamyka okno; zostaje codzienne przypomnienie rano
  (`ogloszenia-przypomnienia-mailem.md`), nic się nie zapisuje.

## Czego nie robić

- Nie przenoś generowania do transakcji tworzenia ani nie czekaj na model
  w odpowiedzi `POST /api/jobs` — model liczy do minuty.
- Nie zapisuj złożenia z pól przy tworzeniu i nie zastępuj ogłoszenia, które ktoś
  zdążył przygotować.
- Nie dokładaj drugiej ścieżki publikacji — panel nie ma własnego zapisu.
- Link z odpowiedzi opiekuna Pracuj.pl NEXUS nadal nie czyta
  (`ogloszenie-pracuj-mailem-do-opiekuna.md`); makieta to pokazywała, ale to nie
  weszło do tego kroku.

Testy: `backend/tests/test_job_ad_on_create.py`,
`frontend/src/components/v2/job-ad/__tests__/AfterCreatePublish.test.tsx`,
`JobAdWindow.test.tsx` (krok po utworzeniu), `job-ad-mail-intent.test.ts`,
`NewJobPage.test.tsx` (przejście `?ogloszenie=nowa`).

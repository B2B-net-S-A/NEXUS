# `/jobs/new`: Powtórka — poprzednia rekrutacja i tylko różnice z maila (wariant 2, 24.11.2026)
<!-- indeks: `RepeatRequestBanner`, `lib/job-intake-repeat.ts` (`repeatTemplate`, `mergeRepeat`, `repeatTakeSummary`), `useSimilarRequests`, „Ta sama osoba co w <nr>”, plakietka „z <nr>”, `applyTemplate(..., { keepCritical })`, `removedRows` w łatce cofnięcia, `recent_channels.from_job_id` -->

Decyzja Artura z 23.11.2026: wariant 2 „Powtórka” jako drugi krok po wariancie 1
(`jobs-new-mniej-decyzji-wariant-1.md`). Makiety: https://claude.ai/artifact/5CT33qwDPP5vurc1CVY7yV,
zakładka „Wariant 2”. Pomiar z kopii produkcji z 23.11: 66 ze 116 nowych rekrutacji (57%) ma
wcześniejszą rekrutację o podobnej nazwie u tego samego klienta. Do tej pory podpowiedź
„U tego klienta było już N podobnych requestów · Użyj jako szablon” stała w lewej kolumnie
pod plikami, poza pierwszym ekranem, a szablon nie przenosił krytycznych, kategorii ani kanałów.

## Kiedy stoi baner

- Po odczycie maila albo pliku **do pustego formularza** (`isPristineIntake` i bez szablonu),
  gdy karta podobnych requestów (`useSimilarRequests`, `POST /api/jobs/request-history/preview`,
  ta sama co `SimilarRequestsBanner`) zwraca coś dla tego klienta. Nie ma własnego progu —
  nowy próg tylko po pomiarze. Plik Profilu Championa (`reader: "champion_form"`) banera nie
  dostaje: to już wypełniony wzór, nie mail.
- Przed odczytem banera nie ma: dopasowanie potrzebuje roli z odczytu.
- Baner stoi nad formularzem, pod paskiem wypełnienia; stary baner w kolumnie requestu jest
  wtedy schowany (jedno zapytanie, ten sam klucz). „Czytaj od zera” chowa baner do następnego
  odczytu, zmiana klienta i wczytanie zapisanego formularza go zdejmują.
- **Pierwsza ręczna zmiana formularza chowa baner** (`editForm` w `NewJobPage`: pola, propozycje,
  kategoria, pozycja z zespołu). „Użyj” składa formularz z migawki odczytu, więc po edycji
  nadpisałby to, co DL wpisał. „Cofnij wypełnienie” po „Użyj” przywraca baner tylko wtedy,
  gdy DL niczego po „Użyj” nie zmienił.
- `<nr>` to numer zapytania klienta (`client_reference`, np. 43260 — tak DL nazywa request),
  a bez niego id rekrutacji (`RepeatTemplate.label`).
- Na górze najlepiej pasująca rekrutacja (największe `similarity`): nazwa od klienta, stan,
  liczba kandydatów, DL. „Inne podobne (N)” pozwala porównać z inną. Kolumny „Weźmiemy z
  <nr>” (`repeatTakeSummary`) i „Z nowego maila” (wynik `mergeRepeat`: co przyjdzie z maila
  i przy jakich polach mail ma inną wartość). Awaria wczytania szablonu jest widoczna
  („Spróbuj ponownie”), „Czytaj od zera” działa dalej.

## „Użyj <nr> i przeczytaj z maila tylko różnice”

- Baza to `repeatTemplate`: `applyTemplate(pusty, …, { keepCritical: true })` — wiersze
  z krytycznymi (`stack.critical`, `[]` = „Brak krytycznych”), pytania z „odpada, gdy”,
  najważniejsze zadanie z zaznaczonym pytaniem (bez `keyTaskProposed` — to już decyzja DL-a
  z poprzedniej rekrutacji), budżet, tryb, miasta, liczba osób, „Klient nie podał” przy
  terminie i kategoria (`categoryConfirmed`). **Termin-data nie przechodzi** — należała do
  starego requestu. Zwykły szablon („Inna rekrutacja”, `?from=`, stary baner) dalej NIE
  przenosi krytycznych; robi to tylko Powtórka.
- Potem `mergeRepeat`: z maila **zawsze** nazwa od klienta z numerem, opis projektu
  i obowiązki (to opis tego requestu). Resztę odczyt tylko dopełnia, jak D3
  (`applyIntakeRead`): puste pole bierze wartość z maila, inna wartość czeka jako propozycja
  „W mailu: …”, nowe wymagania i pytania jako jedna propozycja „jeszcze N …”. Krytyczne
  z maila (M1) nie wchodzą — wiersze są z szablonu.
- **Hiring manager nie kopiuje się po cichu** (u Nordei 36 różnych osób w 47 rekrutacjach).
  Gdy mail go nie podał, przy polu czeka propozycja „Ta sama osoba co w <nr>: …”
  z „Potwierdź” / „Inna osoba” (`IntakeOffer.sourceLabel`, jedzie w autozapisie). HM z maila
  wygrywa — propozycji z szablonu wtedy nie ma.
- Pasek: „Wypełniono z <nr> i z maila (nazwa i numer, opis projektu, …). Różnice z maila do
  decyzji: … / brak.” z „Cofnij wypełnienie”. Przy polach z szablonu plakietka „z <nr>”
  (`templateLabel` w `NewJobReviewForm`) zamiast „z podobnej rekrutacji”.
- **Cofnięcie wraca do formularza z samego odczytu.** Łatka (`intakeFillUndo`) niesie też
  zastąpione wiersze i pytania (`removedRows`, `removedQuestions`), bo Powtórka wymienia
  wiersze odczytu na wiersze szablonu; wszystkie propozycje Powtórki znikają, wracają
  poprzednie. Poprawki zrobione po „Użyj” zostają, jak przy każdym cofnięciu.
- Utworzenie idzie jak przy szablonie: `from_job_id` = <nr>, serwer zapisuje
  `created_from_template` z `source_job_id`.

## Kanały ogłoszenia

- Krok „Ogłoszenie” po „Utwórz” (`ogloszenie-przy-utworzeniu.md`) zaznacza kanały
  rekrutacji-szablonu tego samego klienta (`on_create.recent_channels`: `created_from_template`
  → `source_job_id`), o ile szablon miał jakiekolwiek ogłoszenie; podpis „Zaznaczone jak
  w <nr>.” (`recent_channels.from_job_id`). Szablon bez ogłoszenia albo od innego klienta =
  dotychczasowe „jak w ostatnich rekrutacjach klienta”. Dotyczy każdego tworzenia z szablonu,
  nie tylko Powtórki. Treść ogłoszenia z <nr> nie jest kopiowana — pisze ją model przy
  „Utwórz” jak zawsze.

## Czego nie robić

- Nie kopiuj hiring managera do pola bez „Potwierdź”.
- Nie wprowadzaj własnego progu dopasowania dla banera bez pomiaru — dopasowanie jest to samo
  co w karcie podobnych requestów.
- Nie pokazuj banera po odczycie do formularza, w którym DL coś wpisał: „Użyj” składa formularz
  od nowa.

Testy: `frontend/src/lib/__tests__/job-intake-repeat.test.ts`,
`components/v2/jobs/new/__tests__/RepeatRequestBanner.test.tsx`,
`NewJobPage.test.tsx` (blok „wariant 2 „Powtórka””),
`backend/tests/test_job_ad_on_create.py::test_template_of_the_same_client_gives_its_channels`.

# Rozliczenia: MD ponad dni robocze zaakceptowane przez klienta i faktura KSeF w wątku Time Sheet

<!-- indeks: ponad dni robocze, fields.md_month_limit, MD przy dniach roboczych, zaakceptowane przez klienta, _over_limit_accepted, _client_count, client_count, Verdict.counted, podpis klienta obejmuje, arkusz zbiorczy, signoffs.client_signed, mail z liczbą, akceptacja mniejszej liczby, dwóch klientów, other_md, nadgodziny BNP, extra.mail_before, akceptacja po pracy dodatkowej, faktura KSeF, Krajowy System e-Faktur, Numer KSeF, _is_ksef_invoice, _not_report, _pick_report, Nie rozpoznano szablonu RCP, Wystawione, VeloBank, BNP -->

Od 25.11.2026, po powtórce 8 próby rozliczeń IX–X 2026 (kopia produkcji z nocy
23/24.11). Trzy rozliczenia miały MD zgodne z fakturą Finansów, a czekały na
człowieka, bo MD przekraczały zwykły miesiąc. Finanse przyjęły je ręcznie.

## MD ponad dni robocze, gdy klient zaakceptował tę liczbę

`fields.md_month_limit` daje uwagę „X MD przy N dniach roboczych”, bo więcej MD niż
dni to zwykle zapis za dwóch klientów. Przypadek z próby: Time Sheet z 182 h przy
22 dniach roboczych (22,75 MD). Klient podpisał arkusz zbiorczy z 22,75 MD tej
osoby i Finanse zafakturowały 22,75 MD.

Teraz `service._over_limit_accepted` (po `_signed_checks`) zmienia tę uwagę na „ok”
z dopiskiem „zaakceptowane przez klienta”, gdy klient zaakceptował dokładnie MD
z dowodu (`_client_count`):

- podpisany dokument od klienta (`signoffs.client_signed`, znacznik `by_client`)
  z liczbą MD osoby równą MD z dowodu (do 0,005 MD);
- mail z domeny klienta z liczbą godzin albo MD równą dowodowi
  (`proof.accept_has_hours`, `mail_text.Verdict.counted`, przenoszone w
  `ProofResult.client_count`, które nie trafia do zapisu).

Uwaga zostaje, gdy:

- nie ma akceptacji albo klient zaakceptował mniejszą liczbę;
- arkusz przyszedł od samej osoby (panel, jej adres, jej podpis);
- mail jest spoza domeny klienta, a zrzut ekranu (OCR) nie ma adresu, więc też się
  nie liczy;
- samo „Akceptuję” bez liczby (akceptacja z godzinami z TS) nie obejmuje liczby;
- osoba ma MD u innych klientów w tym miesiącu (`other_md`). To sprawa „ta sama
  osoba na dwóch kontraktach” (BP i VeloBank) i zgodnie z decyzją Artura
  z 24.11.2026 wyjaśniają ją Finanse z osobą.

Inne uwagi rozliczenia zostają bez zmian. Gdy uwaga limitu była jedyną, rozliczenie
przechodzi do „ok”.

## Faktura KSeF w wątku Time Sheet to nie RCP

Konsultant BNP odpisuje w wątku „TS Wrzesień … zatwierdzenie przepracowanych godzin”
„Wystawione” i dołącza wydruk faktury z KSeF. Plik dostaje rodzaj „raport” z tematu.
Był najnowszy, więc `_pick_report` brał go za RCP. Rozliczenie miało „Nie rozpoznano
szablonu RCP” i MD z wcześniejszego odczytu, a podpisany przez klienta RCP
z nadgodzinami leżał obok i nikt go nie sprawdzał.

Teraz `_not_report` odrzuca PDF z nagłówkiem „Krajowy System e-Faktur” i „Numer
KSeF:” (`_is_ksef_invoice`), gdy w miesiącu jest inny plik. Rodzaju pliku przy
wczytaniu poczty to nie zmienia.

## Nadgodziny BNP: akceptacja po pracy zostaje uwagą

Na BNP po tej zmianie kontrole RCP przechodzą: podpis przełożonego z banku ważny,
mail akceptujący pracę dodatkową z domeny banku („wyraziłem zgodę na przepracowane
nadgodziny”). Zostaje `extra.mail_before` „Akceptacja z …, po pracy dodatkowej”.
Decyzja Artura z 13.11.2026: ta reguła zostaje u BNP na „Ostrzega”, bo przełożony
potwierdza nadgodziny po fakcie, razem z RCP. Tej zmiany ta poprawka nie dotyka.

## Pomiar (25.11.2026)

Klon `nexus_staging_klodko_v8`, 371 rozliczeń IX–X przeliczonych w jednej transakcji
z rollbackiem, kod `main` 5d7578404 i kod tej zmiany na tych samych danych.

| Przypadek | `main` | Ta zmiana |
|---|---|---|
| VeloBank X, 22,75 MD przy 22 dniach | uwagi (`fields.md_month_limit`) | ok, 22,75 MD |
| BNP IX, 14 + 9,375 MD | uwagi: „Nie rozpoznano szablonu RCP” (faktura KSeF jako RCP) | uwagi: tylko `extra.mail_before`; RCP odczytany, 14 + 9,375 MD |
| BNP X, 17 + 4,75 MD | uwagi: „Nie rozpoznano szablonu RCP” | uwagi: tylko `extra.mail_before`; 17 + 4,75 MD |

Pozostałe 368 rozliczeń bez zmiany statusu, MD, dokumentu dowodu i kontroli.
W IX–X tylko te dwa rozliczenia BNP mają nadgodziny z akceptacją i w obu akceptacja
jest po pracy dodatkowej.

Powiązane: `rozliczenia-podpisany-arkusz-zbiorczy.md`,
`rozliczenia-falszywe-blokady-przy-zgodnych-md.md`,
`rozliczenia-akceptacja-od-klienta-orlen-cez.md`.

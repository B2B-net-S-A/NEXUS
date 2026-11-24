# Rozliczenia: nadawca i okres raportu z poczty — Gmail bez kropek, erste.pl, „MM RRRR”

<!-- indeks: brak dokumentu, brak wejścia, nadawca rozliczeń, Gmail, kropki w adresie, _by_gmail_alias, googlemail, erste.pl, KNOWN_SENDER_DOMAINS, skrzynka u klienta, _by_company_address, KCP, Bank Pocztowy, period_for, _PERIOD_NUMERIC, okres zgadnięty, period_guessed, zmiana klienta, dwa kontrakty, ENDED_GRACE_DAYS, resolve_sender_in_month, works_in_month, VeloBank 466 467 -->

Od 23.11.2026. W próbie rozliczeń IX–X 2026 (powtórka na kopii produkcji) 24 przypadki poza
Nordeą miały status „bez dokumentu”, choć Finanse wystawiły za nie faktury. Przegląd archiwum
rozliczenia@ i administracja@ pokazał, że w większości raport w poczcie był, a NEXUS nie
łączył go z kontraktem albo z miesiącem. Trzy z tych przyczyn naprawia ta zmiana.

## Reguły

- **Gmail bez kropek.** Gmail pomija kropki w nazwie skrzynki, więc `imie.nazwisko@gmail.com`
  i `imienazwisko@gmail.com` to ta sama skrzynka. Nadawca bez trafienia w adres z kontraktu
  i z kartoteki jest porównywany z adresami z kontraktów w domenach `gmail.com`
  i `googlemail.com` bez kropek (`identity._by_gmail_alias`). Dwie osoby pod tym samym
  adresem albo dwa działające kontrakty = nikt (karta do przypisania), jak przy każdym
  nadawcy. Inne domeny poczty prywatnej (wp.pl, o2.pl) rozróżniają kropki, więc ich to nie
  dotyczy.
- **Skrzynka konsultanta u klienta ERSTE.** Erste Bank Polska (dawny Santander) pisze
  z `erste.pl`, a rejestr domen klientów (`order_policies/known_clients.KNOWN_SENDER_DOMAINS`)
  znał tylko `erstebank.pl`. Konsultant, który wysyła akceptację ze skrzynki
  `imie.nazwisko@erste.pl`, był nieznanym nadawcą. Teraz `_by_company_address` szuka go
  wśród kontraktów ERSTE. Ta sama domena pomaga rozpoznać klienta w poczcie zamówień, gdzie
  domena jest najsłabszym sygnałem i niczego nie zapisuje sama.
- **Okres „MM RRRR” ze spacją.** Karta pracy Banku Pocztowego ma nazwę
  „KCP Nazwisko Imię 09 2026.pdf”. `_PERIOD_NUMERIC` czytał tylko `09.2026`, `09/2026`,
  `09-2026` i `09_2026`, więc taki plik dostawał okres zgadnięty z daty maila: przy mailu
  z 15.09 był to sierpień. Teraz separatorem może być też jedna spacja. Na archiwum
  rozliczenia@ VI 2025 – XI 2026 zmienia to okres 30 z 15 126 plików, w każdym przypadku na
  właściwy miesiąc. Numer bez miesiąca („Umowa 1516 2026”) dalej nie jest okresem.

## Zmiana klienta: raport do kontraktu, który działa w miesiącu raportu (od 24.11.2026)

Zakończony kontrakt działa w czytniku jeszcze 60 dni (`identity.ENDED_GRACE_DAYS`), bo
ostatni raport i faktura przychodzą po końcu współpracy. Osoba po zmianie klienta ma więc
przez dwa miesiące dwa „działające” kontrakty pod jednym adresem, a dwa kontrakty znaczyły
kartę do ręcznego przypisania. W próbie IX–X 2026 Time Sheet za IX dwóch osób z VeloBanku
(466, 467) czekał bez osoby, bo ich adres firmowy wskazywał też kontrakty w Banku Pocztowym
zakończone 31.08 (418, 422). Raport próby podał to jako „brak TS w poczcie”.

- Raport (`kind == "report"`) z okresem w nazwie pliku albo w temacie idzie do jedynego
  kontraktu nadawcy, którego okres (`start_date`–`end_date`) obejmuje choć jeden dzień tego
  miesiąca (`identity.resolve_sender_in_month`, wołane w `mailbox._ingest_message`). Działa
  w obie strony: ostatni raport za miesiąc sprzed startu nowego kontraktu idzie do
  poprzedniego.
- Okres zgadnięty z daty maila (`period_guessed`) niczego nie rozstrzyga, bo plik bez okresu
  bywa spóźnionym raportem poprzedniego kontraktu.
- Faktura też nie: jej numer („FV3_10_2026” w mailu z Time Sheet za IX) niesie miesiąc
  wystawienia, a ostatnia faktura za poprzedni kontrakt przychodzi po jego końcu. Faktura
  czeka na człowieka jak dotąd, tak jak przy osobie z kontraktem u klienta z raportem T4T.
- Tylko kontrakty jednej osoby. Adres dwóch różnych osób, dwa kontrakty działające
  w miesiącu pliku albo żaden = karta do przypisania.
- Miesiąc sprawdzamy przed raportem T4T (`resolve_report_owner`), który bez okresu wybrałby
  kontrakt zakończony przed miesiącem pliku.

Pomiar z 24.11.2026 na kopii produkcji klodko v6r2: poczta rozliczenia@ i administracja@
z okresu 01.09–20.11, ten sam kod (#3909) raz bez poprawki, raz z nią.
- 4 dokumenty dostają osobę, a żaden przypisany dokument nie zmienia osoby. Każdy trafia do
  jedynego kontraktu osoby, który działa w miesiącu pliku:
  - Time Sheet za IX → 466 i 467;
  - akceptacja kierownika (mail w załączniku) → 467;
  - KCP Banku Pocztowego za IX → 412.
- Dochodzi 1 dokument: treść maila z TS 466, zapisana z reguły akceptacji mailowej VeloBanku.
- Rozliczenia IX–X:
  - 466 i 467 za IX dalej „ok”, z MD 20 i 20,5 (TS: 160 h i 164 h), czyli tyle samo, ile
    arkusz zbiorczy i prawda próby. Raportem rozliczenia jest teraz TS;
  - nowe rozliczenie 412 za IX: „ok”, 22 MD (prawda 22);
  - pozostałe 366 bez zmian.
- Faktura z maila z TS za IX („FV3_10_2026”) dalej czeka na człowieka.
- 412 IX to skutek kopii: drugi kontrakt tej osoby wpisano w NEXUS-ie 29.10, po mailu
  z 15.09. Na produkcji tak samo bywa, gdy następny kontrakt jest wpisany przed startem
  (tu tydzień wcześniej), a raport za bieżący miesiąc przychodzi w tym czasie.

## Czego ta zmiana nie robi

Pozostałe przyczyny z tej próby wymagają decyzji albo innej pracy:

- Raport zbiorczy klienta w ZIP-ie (Credit Agricole: arkusz „Raport rozliczenia
  outsourcingu” w ZIP-ie z hasłem; PKO: „Dokumenty.zip” z TS i akceptacją). Czytnik nie
  rozpakowuje ZIP-ów.
- Arkusz `.xls` od klienta z kilkoma osobami i numerem zamówienia (Polkomtel, Cyfrowy
  Polsat), który rozstrzyga też osobę z dwoma kontraktami w grupie.
- Zrzut ekranu w treści maila (akceptacja w Jirze, przekazanie od DL-a z prywatnej skrzynki).
  Zostaje sprawą dla człowieka.
- Osoba z dwoma działającymi kontraktami, gdy nowy kontrakt zaczyna się po miesiącu raportu.
  Od 24.11.2026 raport z okresem rozstrzyga miesiąc (sekcja „Zmiana klienta” wyżej).

Powiązane: `finanse-insights/rozliczenia-odpowiedz-klienta-na-nasz-wyslany-mail.md`,
`finanse-insights/rozliczenia-czytniki-plikow-klientow.md`, `ludzie/portal-konsultanta.md`.

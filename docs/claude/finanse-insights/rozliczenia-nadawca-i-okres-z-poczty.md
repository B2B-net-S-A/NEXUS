# Rozliczenia: nadawca i okres raportu z poczty — Gmail bez kropek, erste.pl, „MM RRRR”

<!-- indeks: brak dokumentu, brak wejścia, nadawca rozliczeń, Gmail, kropki w adresie, _by_gmail_alias, googlemail, erste.pl, KNOWN_SENDER_DOMAINS, skrzynka u klienta, _by_company_address, KCP, Bank Pocztowy, period_for, _PERIOD_NUMERIC, okres zgadnięty, period_guessed -->

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

Powiązane: `finanse-insights/rozliczenia-odpowiedz-klienta-na-nasz-wyslany-mail.md`,
`finanse-insights/rozliczenia-czytniki-plikow-klientow.md`, `ludzie/portal-konsultanta.md`.

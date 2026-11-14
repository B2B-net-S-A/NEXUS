# Księga NEXUSA K3 (14.11.2026): PK cykliczne, RMK, paczka do Symfonii, lista płac z Enovy

Etap K3 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar),
część pierwsza. Fundament: `ksiega-nexusa-k1-fundament.md`, źródła miesiąca:
`ksiega-nexusa-k2-zrodla.md`. Migracja `0701_ledger_automations`
(`ledger_automation_schema.py`, lustro przez `hr_schema_bundle`).

## Co jest

- Moduł `automations` („Podatki, polisy i PK cykliczne”) ma ekrany od K3a
  (`BUILT`), zakładka „Automaty” (`/accounting/automations`). Wyłączony widzi
  tylko admin, jak każdy moduł Księgowości.
- **PK cykliczne** (`ledger_recurring`): wzór z pozycjami dekretu (grosze, MPK,
  kontrahent), pierwszy i opcjonalnie ostatni miesiąc. Co miesiąc w zakresie
  jeden PK w ostatnim dniu miesiąca, źródło `ledger_recurring` / `<id>:RRRR-MM`.
- **RMK** (`ledger_prepayments`, rozliczenia międzyokresowe kosztów czynne, np.
  polisy): kwota całkowita w N ratach od pierwszego miesiąca; rata = kwota // N,
  ostatnia = reszta (suma rat = kwota co do grosza). PK Wn konto kosztu (MPK) /
  Ma konto RMK, źródło `ledger_prepayment` / `<id>:RRRR-MM`.
- Dokumenty powstają w „Źródłach” (to samo „Zaksięguj miesiąc” co faktury:
  odcisk danych, przebudowa szkicu, problem do storna) — karty „PK cykliczne”
  i „RMK” pokazują się przy otwartym module.

## Zasady, których łatwo nie zauważyć

- **Zatwierdzona przeszłość jest nietykalna**: wzoru ani RMK z zatwierdzonym
  miesiącem nie zmienia się i nie usuwa (409). Zmiana kwoty przerobiłaby
  wszystkie zamknięte miesiące na problemy do storna. Wzór kończy się datą
  (`end_month` nie wcześniej niż ostatni zatwierdzony miesiąc); nowa kwota =
  nowy wzór od następnego miesiąca.
- **Szkice znikają od razu**: usunięcie wzoru albo RMK i każda zmiana treści
  zdejmują jego szkice z bufora, a „Zakończ” — szkice po ostatnim miesiącu.
  Następne „Zaksięguj miesiąc” zrobi je od nowa z nowych danych. Czekanie na
  księgowanie zostawiało w buforze szkic ze starymi kwotami, który dało się
  zatwierdzić (przegląd K3a 14.11.2026).
- Wzory i RMK zakłada lista „Księgowi” albo admin; podgląd „Moduł Finanse”
  przy otwartym module. Pozycje wzoru przechodzą tę samą kontrolę co PK
  (konta z planu, Wn = Ma).
- Wycena walut idzie z rozrachunkami w K4.

## Paczka do Symfonii (K3b, migracja `0702_ledger_exports`)

- Zakładka „Do Symfonii” (`/accounting/symfonia`, moduł `ledger`): zatwierdzone
  dokumenty miesiąca w pliku do importu w Symfonii FK, póki Symfonia jest księgą
  urzędową (tryb roku „symfonia” albo „równolegle”; w trybie NEXUS 409).
  Bez paczki PK z „Automatów” trafiałyby tylko do księgi-cienia, a księgowa
  dalej przepisywałaby je ręcznie.
- **Domyślnie w paczce**: PK z ręki, PK cykliczne, RMK, rozliczenie kosztów na
  „5”. Faktury kosztowe (FVZ) mają własną paczkę E2, sprzedaż (FVS) trafia do
  Symfonii z eBI24 do czasu wystawiania w NEXUSIE, bilans otwarcia przychodzi
  z Symfonii — te rodzaje da się zaznaczyć, ale domyślnie są poza paczką, bo
  Symfonia dostałaby je dwa razy. Storno ma rodzaj dokumentu, który odwraca.
- **Dokument najwyżej w jednej aktywnej paczce** (`ledger_export_documents`,
  indeks unikalny częściowy) — paczka zbiera tylko dokumenty spoza paczek.
  Numer `K/RRRR-MM/n` (blokada doradcza), plik i SHA-256 w bazie: ponowne
  pobranie daje ten sam plik. „Zaksięgowana w Symfonii” zamyka paczkę;
  „Anuluj” (tylko pobraną) zwalnia jej dokumenty do następnej.
- **D2**: dokumenty płacowe idą wyłącznie osobną paczką płacową (robi i widzi
  ją osoba z Płacami albo admin). Mieszana paczka zabrałaby zwykłe dokumenty
  z widoku osoby bez Płac, a samej paczki ta osoba by nie zobaczyła.
- Paczkę, „zaksięgowaną” i anulowanie robi lista „Księgowi” albo admin;
  podgląd i pobranie pliku — „Moduł Finanse”.
- Plik: format neutralny jak w E2 (XLSX albo CSV, wiersz na pozycję dekretu:
  nr w dzienniku, numer, typ, daty, konto, Wn/Ma, MPK, kontrahent z ID
  Symfonii, waluta, storno dokumentu, numer KSeF). Identyfikator kontrahenta
  tylko NIP albo VAT UE — PESEL z kartoteki E1 nie trafia do pliku. Format
  importu Symfonii FK dopiszemy klasą w `ledger/export_file.py` po próbce od
  Finansów.

## Lista zamknięcia miesiąca i terminy (K3d, bez migracji)

- Zakładka „Miesiąc” (`GET /closing`) zamiast statycznej listy źródeł: stan
  każdego źródła z „Źródeł” (do zaksięgowania, do wyjaśnienia), bufor,
  paczka do Symfonii (dokumenty domyślnych rodzajów poza paczką i paczki
  czekające na „Zaksięgowana w Symfonii”; tylko tryb „symfonia” albo
  „równolegle”) i etapy w drodze (K4–K7) z tym, kto je robi do tego czasu.
  Odnośnik „Przejdź” tylko przy brakach. Liczby są te same co na tamtych
  ekranach, także D2 (osoba bez Płac nie widzi dokumentów płacowych).
- **Terminy za miesiąc M przypadają w M+1**: ZUS i PPK — 15., PIT-4 (zaliczki
  od wynagrodzeń pobrane w M) — 20., VAT i JPK_V7M — 25. Sobota, niedziela
  i święto przesuwają termin na następny dzień roboczy (art. 12 § 5 Ordynacji
  podatkowej) — kalendarz świąt jak `scheduling.is_business_day`. Kwoty dojdą
  z listą płac (K3c, K7) i rozliczeniem VAT (K5).
- Zapis i usunięcie automatu odświeżają całą księgę na froncie, bo zdejmują
  szkice z bufora (liczniki okresów, dokumenty, lista zamknięcia).

## Lista płac z Enovy (K3c, bez migracji, do czasu Płac w NEXUSIE — K7)

- „Automaty” → „Lista płac z Enovy” (`POST /payroll-lists/import`): plik listy
  (XLSX/CSV, wiersz na osobę) → podgląd sum i dekretu → dokument **LP** w buforze,
  źródło `payroll_list` / `RRRR-MM:<lista>`, wrażliwość `payroll`. **Tylko Płace
  i admin** (D2) — karta, trasa (403) i liczby na liście zamknięcia. Ponowny import
  tej samej listy przebudowuje szkic; zatwierdzony LP poprawia się stornem (409).
- Formatu eksportu Enovy nie znamy z próbki — kolumny rozpoznajemy po słowach
  w nagłówku (nie po przedrostkach). **Nagłówek ze znacznikiem pracodawcy**
  („pracodawca”, „firma”, „płatnik”, „zakład”) nigdy nie trafia do kwot
  pracownika; nieprzypisany = odmowa pliku. **Dwie kolumny tej samej pozycji =
  odmowa** (poza potrąceniami, które się sumują). Kolumna łączna („ZUS
  pracownika/pracodawcy”) obok niepełnego rozbicia = odmowa, obok pełnego musi
  się zgadzać co do grosza. „Netto” liczy się tylko bez „Do wypłaty”. Podstawy,
  koszty uzyskania i składniki brutto pomijamy. Podgląd pokazuje, jak
  rozpoznano kolumny.
- **Wszystko, przez co LP wyszedłby zbilansowany, ale z innymi kwotami niż
  lista, blokuje zapis** (przegląd K3c): brutto − potrącenia ≠ „Do wypłaty”,
  wiersz „Razem” ≠ suma osób, brak kolumny „Do wypłaty”, składki ZUS pracownika
  bez żadnej składki pracodawcy. Wiersz sumy poznajemy po pierwszym słowie
  („Razem”, „Suma”…) w dowolnej komórce tekstowej — „Sumała” to nazwisko.
- Zatwierdzony LP jest domyślnie w paczce płacowej do Symfonii (rodzaj „Listy
  płac (Enova)”), a lista zamknięcia liczy go do „zatwierdzone poza paczką”.
- Dekret: Wn wynagrodzenia i Wn koszt pracodawcy (składki, FP, FS, FGŚP, PPK)
  z MPK z kolumny „Wydział”, Wn rozrachunki z tytułu wynagrodzeń (potrącenia);
  Ma rozrachunki (brutto), ZUS, US (PIT-4), PPK, inne potrącenia. Netto zostaje
  na rozrachunkach do wypłaty (rozliczy je wyciąg w K4).
- Nieczytelna kwota, brak kont albo ujemne sumy też blokują.
- Konta (`PUT /config/payroll`, admin): wynagrodzenia, koszt pracodawcy,
  rozrachunki z tytułu wynagrodzeń, ZUS i US wymagane; PPK i inne potrącenia
  opcjonalne — lista z takimi kwotami bez konta czeka z problemem.

# Rejestr aneksów, aneks w kontrakcie od wygenerowania, podpis ze skanem — raport z wdrożenia

13.10.2026. Reguła: `docs/claude/kontrakty/rejestr-aneksow-i-aneks-w-kontrakcie.md`.
Makiety: https://claude.ai/artifact/T6mGQ6YsgZCiuXzSWZzG3b. Harness: `/preview/b2b-documents`.

## Po co

Ticket działu („Generator aneksów + zakładka Aneksy”, 14 punktów) opisywał brak rejestru
aneksów, statusów i śladu aneksu w kontrakcie. Przegląd kodu przed pracą pokazał, że około
połowy już działało (tabela `b2b_contract_documents`, lista w „Dokumentach”, „Oznacz jako
podpisany” ze skutkami w kontrakcie), a prawdziwe luki były inne niż w tickecie:

1. Aneks do „Umowy spoza Nexusa” nie był zapisywany wcale — nie było go w żadnej liście
   i podpis nie zmieniał kontraktu. To samo dotyczyło aneksu do umowy z Excela bez kontraktu.
2. Lista aneksów była w innej zakładce niż ich tworzenie i nie mówiła, dla kogo jest aneks,
   co zmienia ani od kiedy.
3. Kontrakt pokazywał aneks dopiero po podpisie, a aneksy z generatora (poza stawką) miały
   tam pusty tytuł.
4. Wiersz „Umów bieżących” zmieniał firmę, NIP i datę startu po cichu przy wygenerowaniu.
5. Do Dokumentów kontraktu trafiał wygenerowany DOCX, nie skan z podpisami.

## Co weszło

Jeden PR, bez migracji (kolumny już były; data wejścia w życie i id skanu idą do
istniejącego `effect_summary`).

- **Każdy aneks jest zapisywany.** Aneks bez umowy w rejestrze niesie kontrakt (osobę,
  rekrutację i klienta bierze serwer z kontraktu) albo — gdy osoby nie ma w kontraktach —
  klienta i oznaczenie „Bez kontraktu”; podpis czeka wtedy na powiązanie.
- **Rejestr aneksów w zakładce „Generator aneksów”**: dla kogo, typ, zmiana, dzień wejścia
  w życie, jeden stan, kontrakt, autor; wyszukiwarka (osoba, firma, NIP, numer umowy), filtry
  typu i stanu, akcje: pobierz, popraw, oznacz jako podpisany, anuluj, przywróć, powiąż
  z kontraktem, historia. Zakładkę widzi każdy użytkownik generatora; „Dokumenty” pokazują
  pozostałe rodziny.
- **Jedno wyszukiwanie „Dla kogo jest aneks?”** zamiast przycisku „Umowa spoza Nexusa”:
  umowy z rejestru i kontrakty bez umowy w rejestrze w jednej liście.
- **Umowa z Excela działu** dowiązuje się do trwającego kontraktu osoby przy wygenerowaniu
  aneksu (jedyny dopasowany sam, przy kilku tylko wskazany).
- **Skan podpisanego aneksu** (PDF, JPG, PNG do 20 MB) w oknie podpisu i z zakładki
  kontraktu; trafia do Dokumentów kontraktu, wygenerowany DOCX zostaje obok.
- **Zakładka „Aneksy” kontraktu jako tabela**: aneks z generatora widać od wygenerowania
  („Czeka na podpis”, z tym, co zmieni podpis), po podpisie wiadomo, skąd jest i jaki ma
  plik; nazwy wszystkich ośmiu typów zmian.
- **Wiersz „Umów bieżących”** mówi o najnowszym aneksie i jego stanie; data startu przed
  podpisem to „stara → nowa”, po podpisie stara przekreślona.
- Przewodnik Jarvisa ekranu generatora, wpisy w inwentarzu funkcji, harness.

## Decyzje i odstępstwa od ticketu i makiet

| Temat | Ticket / makieta | Wdrożone | Powód |
|---|---|---|---|
| Status | dwie kolumny: status aneksu i status podpisu | jeden stan: czeka na podpis · podpisany, wejdzie w życie · obowiązuje · anulowany | przy aneksie obie osie mówią to samo, a „aktywny” przed dniem wejścia w życie byłby nieprawdą |
| „Zmień status” z listy | ręczna zmiana statusu z historią | „Oznacz jako podpisany”, „Anuluj”, „Przywróć” + historia z dziennika zdarzeń | „podpisany” ma skutki w kontrakcie — ustawia go tylko ścieżka, która je stosuje |
| Osoba bez kontraktu | — | aneks „Bez kontraktu” wymaga klienta, podpis po powiązaniu | bez klienta dokumentu nie widziałby Delivery Lead; bez kontraktu podpis niczego by nie zmienił |
| Skan | wymagany przy podpisie | opcjonalny, do dołączenia później | skan bywa dosyłany po fakcie; brak skanu nie może blokować zmiany stawki |
| Miejsce listy | zakładka „Dokumenty” | zakładka „Generator aneksów” | lista obok kreatora, w którym aneks powstaje |
| Stawka „przed” w rejestrze | „przed → po” zawsze | przy umowie spoza Nexusa tylko nowa stawka; „przed → po” w kontrakcie | autor aneksu przechodzi bramkę stawek jako autor — migawka ujawniałaby mu stawkę kontraktu |
| „Umowy bieżące” | linia „przed aneksem: osoba” | bez nazwiska w komórce Partner | kolumna z zasady nie pokazuje nazwiska |
| Aneks w kontrakcie przed podpisem | wiersz historii aneksów | rzut dokumentu, nie wiersz `contract_amendments` | tę tabelę jako zmiany już zastosowane czytają analityka, fakty zamówień i Finanse |

Makiet na kanwie nie aktualizowałem do tych odstępstw.

## Przegląd przed scaleniem

Dwa niezależne przeglądy (kod, bezpieczeństwo); każdą uwagę sprawdziłem w kodzie przed
poprawką. Wszystkie poniższe są naprawione w tym PR-ze.

| Uwaga | Co było źle | Poprawka | Test |
|---|---|---|---|
| Kontrakty w wyszukiwarce osoby | `GET /documents/subjects` oddawał kontrakt (id, status, start) każdemu, kto generuje dokumenty — także rekruterowi i Delivery Leadowi spoza portfela | wiersze kontraktów i kontrakty pod umową tylko dla osoby z prawem edycji kontraktów i zapisem w Delivery, w granicy portfela; odmowa to pusta lista | `test_subjects_keep_contracts_inside_delivery_access` |
| Wiązanie aneksu z kontraktem | `contract_id` w żądaniu, dowiązanie wiersza i „Powiąż z kontraktem” pytały tylko o prawo generatora, które poza Delivery Leadem nie ma zakresu klienta | ta sama para uprawnień w czterech miejscach; bez niej aneks powstaje, wiersz zostaje bez kontraktu | `test_recruiter_cannot_bind_an_annex_to_a_contract`, `test_annex_by_a_recruiter_does_not_link_the_register_row` |
| „Popraw” zamrażał wiersz rejestru | po poprawce aneksu wiersz „Umów bieżących” trzymał starą wartość na zawsze — nie ruszało jej anulowanie, przywrócenie ani kolejny aneks (błąd sprzed tej zmiany) | poprawka przenosi `register_applied`, przeliczenie zna wartość sprzed niej | `test_corrected_annex_moves_the_register_row_and_stays_reversible` (bez bazy), `test_correcting_an_annex_moves_the_register_row` |
| Wejście z kontraktu | kreator brał pierwszy wynik; nowsza umowa tej osoby bez powiązania wypierała umowę powiązaną z kontraktem | umowa powiązana wygrywa; umowa bez powiązania tylko dla aneksu i tylko gdy jest jedna | `test_subjects_from_a_contract_prefer_its_own_agreement` |
| Aneks zlecenia „Bez kontraktu” | dawał się podpisać bez skutku, potem nie dało się go powiązać | czeka na powiązanie jak pozostałe typy | `test_every_annex_that_takes_a_contract_waits_for_it_before_signature`, `test_mandate_annex_without_contract_waits_for_linking` |
| Podmieniony skan a SharePoint | skan podmieniony po wysyłce do SharePointa zostawał tam w starej wersji — dokument z plikiem w SharePoincie nie wracał do wysyłki | podmieniony skan wraca na „czeka”, synchronizacja podmienia treść tego samego pliku; plakietka mówi „w SharePoincie poprzednia wersja” | `test_replaced_scan_overwrites_the_same_sharepoint_file`, `test_file_nexus_did_not_send_is_never_overwritten` (bez bazy), dopisek w `test_signed_scan_lands_in_contract_documents_and_on_the_amendment` |
| Plik skanu przed commitem | podmiana nadpisywała albo usuwała plik na dysku przed zapisem w bazie | nowy plik pod kluczem z treści, stary znika po commicie | ten sam test skanu (stary plik znika, nowy jest na dysku) |

Świadomie nie wdrożone: ograniczenie „Powiąż z kontraktem” do autora aneksu. Aneks „Bez
kontraktu” przygotowany przez rekrutera ma wiązać osoba prowadząca kontrakty; granicą jest
prawo edycji kontraktów u klienta kontraktu i zapis u klienta dokumentu.

## Weryfikacja

- Testy z bazą (CI, sito na PR-ze): kroki 1–8 — 964 zielone (bieg 38377353955); dokumentacja
  i front — bieg 38380764943 zielony; poprawki po przeglądach — patrz opis PR-a (bieg po
  ostatnim commicie).
- Testy bez bazy lokalnie: `test_b2b_annex_rules.py` 17 zielonych (cztery dopisane po
  przeglądach najpierw padały); strażnicy uprawnień, sekcji, stempli, indeksu reguł
  i wgrywania plików — 104 zielone; strażnik kolejności blokad zielony.
- Front lokalnie: `tsc` bez błędów, ESLint czysty na zmienionych plikach, testy generatora,
  zakładki kontraktu i harnessów — 191 zielonych, strażnicy źródeł — 208 zielonych,
  `check-unreachable-modules` bez nowych modułów.
- Ekran: harness `/preview/b2b-documents` w 1280 × 720 — rejestr, wybór osoby, zakładka
  kontraktu, okno podpisu ze skanem; bez przewijania strony w poziomie, zero zapytań do API.

## Niepotwierdzone

- Przeklikanie na produkcji po wdrożeniu (wymaga zalogowanej przeglądarki albo zgody na
  odczyt produkcji).
- Liczby z produkcji: ile aneksów czeka dziś na podpis, ile umów z Excela nie ma kontraktu,
  ile wierszy „Umów bieżących” zamroziła wcześniej poprawka aneksu.
- Widok wyboru osoby dla konta bez prawa edycji kontraktów sprawdzony testem komponentu,
  nie zrzutem (różni się wyłącznie tekstami).
- Podmiana treści pliku w SharePoincie sprawdzona na podmienionym kliencie Graph, nie na
  prawdziwej bibliotece: nie wiem, czy synchronizacja jest włączona na produkcji ani czy
  biblioteka prowadzi historię wersji. Zmiana nazwy pliku z parametrem konfliktu nazwy
  opiera się na dokumentacji Graph — przy odmowie zostaje stara nazwa (ten sam typ pliku)
  albo podmiana jest ponawiana (inny typ).

## Skutki uboczne i ryzyka

- Rekruter i Head of Recruitment nie wybiorą kontraktu spoza rejestru — przygotują aneks do
  umowy z rejestru albo „Bez kontraktu”; powiąże go osoba prowadząca kontrakty.
- Niepodpisane aneksy zlecenia bez kontraktu sprzed wdrożenia trzeba powiązać, zanim da się
  je oznaczyć jako podpisane.
- Wiersze „Umów bieżących” zamrożone przez „Popraw” przed wdrożeniem zostają z wartością
  sprzed poprawki — kod nie odróżni ich od zmiany spoza generatora.
- Skan aneksu danych firmy albo zlecenia zawiera dane osobowe; trafia do Dokumentów kontraktu
  i — przy włączonej synchronizacji — do folderu osoby w SharePoincie, jak plik dołączany
  tam dziś ręcznie. Podmieniony skan zastępuje tam treść tego samego pliku przy
  najbliższej synchronizacji.
- Otwarta stara karta dostanie odmowę przy aneksie spoza Nexusa do czasu odświeżenia (karta
  sama przechodzi na nową wersję frontu).
- Aneksów spoza Nexusa wystawionych przed wdrożeniem nie da się odtworzyć — nie były
  zapisywane.

## Poza zakresem

- Aneks „Osoba skierowana” do umowy spoza Nexusa (wzór cytuje paragrafy umowy z rejestru).
- Cofanie podpisu aneksu, numeracja aneksów, ręczne dopisywanie historycznych aneksów.
- „Wstecz” w kreatorze po wejściu z kontraktu wraca do wyboru typu, nie do wyboru osoby.
- Kolory przycisków w zakładce „Aneksy” (bez zmian, zgodnie z ticketem).

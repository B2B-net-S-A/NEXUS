# Znacznik „Pracuje u nas” — jedna reguła na każdym ekranie (12.10.2026)

<!-- indeks: znacznik zatrudnienia przy osobie (pracuje / kończy / zaczyna u nas), koniec zamówienia i Delivery Lead, okna dodawania do rekrutacji, Tablica, „Potwierdź zatrudnienie”, dzwonek do Delivery Leada obecnego klienta -->

Zgłoszenie Artura: osobę, która u nas pracuje (umowa + zamówienie), dało się
wyszukać i dodać do rekrutacji, a po drodze nigdzie nie było widać, że pracuje
— dopiero na profilu. Dane były w API (`employment`), ale czytał je tylko
profil, szybki podgląd i kolumna „W procesie” listy. Makiety i decyzje D1–D5:
https://claude.ai/artifact/QekWy3zx3pXNEKDKQmikf6, raport:
`docs/employment-marker-completion-report.md`.

## Reguła

- **Jedno źródło: `services/employment_marker.py`.** Czysta `build_markers`
  rozstrzyga fazę, źródło i klientów; każdy ekran czyta jej wynik jako pole
  `employment_marker`. Nowy ekran z osobą = to pole, nie własne wyliczenie
  z umów.
- **Fazy:** „pracuje” = żywa umowa (`active` / `ending`) ze startem nie później
  niż dziś albo bez daty (`current_employment.is_live_contract`); „zaczyna” =
  żywa umowa ze startem w przyszłości; „kończy” = do końca łańcucha zamówień
  bez kontynuacji zostało najwyżej 30 dni. Podpis w Generatorze aktywuje
  umowę od razu i przesuwa kartę na „Zatrudniony”, więc ta sama umowa wygrywa
  z sygnałem `hired` — znacznik mówi „zaczyna”, nie „pracuje”.
- **Stare pole `employment` zostaje.** `employed_at_client` znaczy „ma u nas
  żywą umowę albo sygnał zatrudnienia”, także przed dniem startu — filtr listy
  „Otwarci” nie może łapać osoby z podpisaną umową. Niezmiennik w teście:
  `employed_at_client` ⇔ znacznik istnieje. `contractor_identity.is_current_contract`
  (sama data startu) to reguła kwot i zostaje osobno.
- **Data w znaczniku to koniec zamówień, nie umowy** (umowa B2B jest
  bezterminowa): koniec łańcucha bez kontynuacji wg `order_continuation` — to
  samo, co pokazuje lista kontraktorów. Zamówienie do końca miesiąca
  z przedłużeniem nie daje „do końca miesiąca”. Bez daty: zamówienie
  bezterminowe, brak zamówień, aktywna linia MD z budżetem.
- **„Kończy” idzie za regułą alertów Delivery**, nie za zakładką „Kończące się
  30d”: linie zamówień MD „kończą się” tylko u klientów
  z `EXTENDED_ORDER_ALERT_CLIENT_IDS`. Zakładka liczy grupy MD na froncie
  u każdego klienta — ten rozjazd istniał wcześniej.
- **Znacznik niczego nie blokuje** (jak konflikty z klientem od 17.09.2026)
  i nie niesie kwot, więc widzi go każda rola operacyjna. „Kontrakt ›” w ramce
  tylko z dostępem do sekcji Delivery.
- **Rekruter widzi przez znacznik klienta, koniec zamówienia i Delivery Leada**
  także bez dostępu do zamówień w Delivery, a filtr „Kończy u nas w ciągu 60
  dni” daje mu taką listę dla całej bazy. To cel znacznika (makiety 1–4 i 6
  zatwierdzone przez Artura), nie przeciek. Znacznik nie niesie i nie może
  zacząć nieść stawek, numerów ani treści zamówień — nowe pole z zamówienia
  w znaczniku to zmiana dostępu, do decyzji Artura.
- **`elsewhere`** jest liczone tylko, gdy znany jest klient rekrutacji: `true`
  = któryś klient znacznika jest spoza rodziny klienta tej rekrutacji, `false`
  = to klient tej rekrutacji. Przy `false` pigułka mówi „Pracuje u tego
  klienta” i zastępuje plakietkę `client_current_employment` (bez dubla —
  `markerCoversEligibility`).

## Gdzie i jak

- **Koszt.** Lista kandydatów składa wiersze z relacji już wczytanych
  (`rows_from_candidate`), więc nie dokłada zapytań o źródła; zamówienia
  i Delivery Leadzi dochodzą tylko, gdy na stronie jest ktoś z sygnałem.
  Pozostałe ekrany: jedno zapytanie o źródła na stronę
  (`load_employment_markers`). Pulpit „Moje następne kroki” składa do 25
  tablic w pętli i znacznika nie niesie (`with_employment=False`).
- **Front:** treść w `lib/employment-marker.ts`, pigułka
  `ds/EmploymentPill`, ramka `v2/employment/EmploymentNotice`. Pigułka stoi
  OBOK nazwiska, nigdy w przycisku nazwiska ani w linii faktów — ich treść
  jest nazwą dostępną i tekstem, po którym szukają testy. `lib/employment-marker.ts`
  nie importuje wartości z `@/lib/api` (testy okien mockują tamte moduły wąsko).
- **Panel osoby:** krótka pigułka w rzędzie odznak, ramka w dymku. Stała
  ramka zabrałaby treści panelu wysokość — test `e2e/responsive-preview.spec.ts`
  wymaga 350 px przy 1280 × 650.
- **Lista:** znacznik stoi pod nazwiskiem (kolumna „Kandydat” jest wymagana,
  „W procesie” da się ukryć), a „W procesie” liczy rekrutacje w toku. Filtr
  w pigułce „Dostępność”: `employment=at_client` („Pracuje u nas”)
  i `employment=ending_soon` („Kończy u nas w ciągu 60 dni”); jedna lista
  wartości `EMPLOYMENT_FILTER_VALUES`. Filtr działa dla jednej wartości
  i zostaje „tylko lista” (drugi silnik go nie ma).
- **Okno „Dodaj do rekrutacji”** dostaje osoby pracujące propsem `employed`
  od ekranu, który je otwiera — bez osobnej trasy. Zaznaczenie odtworzone
  z adresu dla osób spoza wczytanych stron nie ma danych do ramki.
- **Tablica rysuje ostrzeżenia pary**, które serwer wysyłał w `warnings`
  (NDA, czarna lista klienta, konkurent…) — jedna mapa etykiet
  `lib/eligibility-reason-labels.ts`, na karcie i w wierszu tabeli.
- **„Moi ludzie”:** osobę z grupy „Pracują” można dodać do rekrutacji (D5);
  grupa i pigułka idą z jednego wyniku. Automat dopasowań i narzędzia Jarvisa
  dalej pomijają pracujących.

## Zatrudnienie i dzwonek (D3, D4)

- **„Potwierdź zatrudnienie”** pyta „Co z obecną współpracą?”, gdy karta
  niesie znacznik z `elsewhere=true`. Odpowiedź
  (`StageMove.hired_current_engagement`) jest opcjonalna na serwerze, wymagana
  w oknie; serwer zapisuje ją tylko, gdy osoba faktycznie ma zatrudnienie
  u innego klienta. Trafia do historii ruchu i na oś czasu profilu (trzy akcje
  `candidate_hired_engagement_*` — oś nie czyta `details`).
- **Okno niczego nie zmienia w umowach i zamówieniach.** Zakończenie
  współpracy dalej zaczyna się w oknie zakończenia (`/terminate`).
- **Dzwonek `consultant_in_other_recruitment`** (0430,
  `services/consultant_elsewhere_notifications.py`): do Delivery Leadów
  klienta, u którego osoba pracuje, gdy karta wchodzi na „CV wysłane”
  w rekrutacji u innego klienta (raz na parę osoba–rekrutacja) albo gdy osoba
  zostaje tam zatrudniona. Samo dodanie do rekrutacji nie dzwoni.
- **Jedno wpięcie:** `stage_notification_emitter.notify_stage_change` — przez
  nie idzie ruch pojedynczy, zbiorczy, automat i podpis w Generatorze. Po
  commicie ruchu; błąd dzwonka nie cofa ruchu. Cały dzwonek stoi
  w savepoincie, bo jest wołany przed regułami etapów w tej samej sesji —
  nieudane zapytanie bez savepointu zabrałoby zwykłe dzwonki tego ruchu.
- **Odbiorcy:** `bell_recipients` (admini tylko jako zapas); autora ruchu
  odsiewamy PO wyznaczeniu odbiorców — odsianie przed dałoby zapas na adminów
  zawsze, gdy kartę rusza jedyny Delivery Lead klienta.
- „CV wysłane” rozpoznajemy po kolumnie Tablicy, nie po kodzie etapu (etapy
  z szablonów Traffita mają inne kody); ruch wstecz nie dzwoni.

# Dzwonienie: Elevate, akcje zbiorcze, grupy kolejki, mail po ofercie, numer z +48 — decyzje Artura 27.11.2026
<!-- indeks: BE Leady Elevate nazwa kampanii, przełącznik grup kolejki QUEUE_GROUPS ?group=, Oddzwonienie na dziś Nieodebrane Nowe rekordy Spotkania bez terminu, następna w grupie, formatPhone 48XXXXXXXXX, dialablePhone Kopiuj numer z plusem, akcje zbiorcze w Tabeli removed_at Cofnij, przeniesienie do kampanii bramka importu, mail po Oferta ogólna wysłana szablon per kampania -->

Powód: lista „Nexus - zmiany do wdrożenia”, punkt 3 (moduł Sprzedaż / Dzwonienie), pięć próśb
osób dzwoniących. Makiety z wariantami na kopii produkcji; Artur 27.11.2026 wybrał wszystkie
rekomendowane (A).

## 1. „BE Leady” → „Elevate”

Tylko nazwa kampanii (id 1), zmieniona 27.11 w „Kampanie → Edytuj” na produkcji. „Skąd kontakt”
zostaje: rekordy z „Lista BE Leady e-commerce” należą do innej kampanii („Audyt dopłat
kurierskich”), więc masowa podmiana źródła przekłamałaby pochodzenie listy.

## 3. Grupy kolejki (zrobione)

Nad listą i kartą przełącznik: Wszystko, Oddzwonienie na dziś, Nieodebrane, Nowe rekordy,
Spotkania bez terminu — z licznikami z serwera (`counts`, nie liczba pozycji na liście, która
jest przycięta do 300 / 100). Lista pokazuje tylko wybraną grupę, a „następna osoba” po zapisie
zostaje w tej grupie (`groupItems` w `calling.ts`). Wybór w adresie (`?group=no_answer`), więc
link może otworzyć grupę od razu; „Wszystko” zdejmuje parametr. Pusta grupa mówi, ile czeka
w pozostałych. Bez zmian w API. Grupy już były (sekcje jedna pod drugą), ale żeby zacząć od
nowych rekordów, trzeba było przewinąć kilkaset oddzwonień i nieodebranych.

## 5. Numer w trójkach i kopiowanie z plusem (zrobione)

83% numerów list dzwonienia jest zapisanych jako „48XXXXXXXXX” (kierunkowy bez plusa).
`formatPhone` czyta je jako polski numer: „+48 514 641 516” (na wszystkich ekranach, nie tylko
w Dzwonieniu — 11 cyfr zaczynających się od 48 nie jest numerem krajowym żadnego kraju).
„Kopiuj numer” na karcie kopiuje `dialablePhone`: „+48514641516”, bo bez plusa telefon wybiera
ciąg jak numer krajowy i połączenie nie wychodzi. W bazie numer zostaje tak, jak go zapisano.
Numer ma `whitespace-nowrap`: ze spacjami łamał się w kolumnę obok przycisku LinkedIn.

## 2. Akcje zbiorcze w Tabeli (do zbudowania, osobny PR z migracją)

Zaznaczanie wierszy w Tabeli i pasek: „Przypisz osobie”, „Przenieś do kampanii”, „Usuń z listy”.
Usunięcie jest miękkie (`removed_at`): rekord znika z kolejki, Tabeli, Przypomnień i liczników,
historia telefonów i firma zostają, przez chwilę jest „Cofnij”. Kolejny import tego samego NIP-u
go nie przywraca (bramka importu widzi usunięte). Przeniesienie korzysta z bramki „już w kampanii”.
„Umówione spotkanie” się nie usuwa (ma szansę w lejku). Usuwa każdy z „Sprzedaż: edycja”.

## 4. Mail po „Oferta ogólna wysłana” (czeka na treści szablonów)

Szablon per kampania (temat, treść, PDF). Panel na karcie nad przyciskami terminu: adres (54%
ofert nie ma e-maila), podgląd; klik terminu = zapis wyniku i wysyłka z Outlooka osoby dzwoniącej
(ta sama droga co mail po umówieniu spotkania, `dzwonienie-mail-po-umowieniu-spotkania.md`).
Bez adresu wynik zapisuje się bez maila. Zmiana statusu w Tabeli maila nie wysyła.

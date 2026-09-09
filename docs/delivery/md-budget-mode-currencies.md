# Zamówienia MD i waluty linii

Nowe zamówienie MD pozwala wybrać budżet per osoba (domyślnie) albo wspólną pulę. Formularz zapisuje szkic, do którego dodaje się konsultantów. W edycji szkicu można zmienić tryb i aktywować zamówienie. Zmiana trybu usuwa podział szkicu; przy powrocie do trybu per osoba trzeba uzupełnić indywidualne budżety przed aktywacją.

Aktywacja lub pierwszy wpis zużycia blokują zmianę trybu. Import finansowy sumuje MD konsultantów we wspólnej puli. Edycja zamówienia umożliwia także zapis łącznego zużycia za miesiąc; ponowny zapis zastępuje poprzednią sumę tego miesiąca. Podgląd i Excel pokazują wspólny budżet raz, bez mnożenia przez liczbę osób.

Migracja dodaje pola i status szkicu. Nie przepisuje historycznych budżetów. Dotychczasowe per-osoba MD pozostają per osoba, a istniejące świadome pule CP/Lotte zachowują swój tryb.

Edycja linii pokazuje osobne waluty pod odpowiadającymi im stawkami. Surowe stawki i waluty są zapisywane osobno od pomocniczych stawek PLN/MD. Zmiana waluty nie przelicza wartości wpisanej w formularzu. Backend przelicza pomocnicze wartości według istniejącego mechanizmu FX, odmawiając zapisu, jeśli brakuje kursu.

## Korekta produkcyjna objęta zgłoszeniem

Bosch (klient 19), Rahan Shetty (kandydat 443352), zamówienie 0087020279. Przed zmianą na produkcji potwierdzono: stawka kosztowa 176, przychodowa 218,75, budżet i pozostałość 98,5 MD, koniec 2026-12-31. Po wdrożeniu poprawić walutę przychodową zamówienia na EUR, zachowując liczbę 218,75, budżet, daty i stronę kosztową. Wykonać przez poprawiony formularz, sprawdzić zapis po ponownym otwarciu i odświeżeniu strony. Nie zmieniać kontraktu ani innych zamówień klienta.

# Dokumenty konsultantów u Finansów (faktura i raport z poczty rozliczeniowej)
Reguły: `docs/claude/finanse-insights/rozliczenia-nadawca-i-okres-z-poczty.md`,
`docs/claude/ludzie/portal-konsultanta.md` (sekcja „Rozliczenia”).

1. Finanse: `/back-office` → karta „Faktura bez kontraktu” → pobierz plik → „Miesiąc
   usługi”, numer kontraktu (przycisk z kontraktem nadawcy albo wpisany), „Przypisz”.
   Nieznany nadawca: bez przycisków, samo pole.
2. Finanse: karta faktury stoi na kontrakcie i wybranym miesiącu; „Przyjmij fakturę”
   albo „Do poprawy”.
3. Finanse: karta „Raport bez kontraktu” → „Miesiąc usługi” inny niż z czytnika →
   „Przypisz”; raport stoi na wybranym miesiącu z dopiskiem „okres nie z nazwy pliku”,
   rozliczenie tego miesiąca się przelicza.
4. Admin: ta sama karta i formularz jak u Finansów.
5. Delivery Lead spoza zespołu back office: bez kart dokumentów na `/back-office`.

Ma nie widzieć: Delivery Lead (spoza zespołu) i Rekruter — dokumentów (403 z
`/api/back-office/portal/documents/…`).
Nie na stagingu: mail do konsultanta po „Do poprawy” (poczta wyłączona) i nowy mail na
rozliczenia@ (M365 wyłączony) — użyj dokumentu z kopii. Karty odświeża przy przypisaniu
sam endpoint; pętla kart stoi.

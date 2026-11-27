# Scenariusz: Udostępnij rekrutację → Post na LinkedIn

Reguła: `docs/claude/rekrutacja-tworzenie/grafika-posta-na-linkedin.md`,
strona kariery: `docs/claude/rekrutacja-tworzenie/strona-kariery-dla-kandydatow.md`.

Kto → co robi → co widzi następny:

1. **Rekruter** otwiera swoją opublikowaną rekrutację z zatwierdzonym opisem
   i linkiem → Profil Championa → „Zespół i ogłoszenie” → „Wygeneruj link
   aplikacyjny” → zakładka „Post na LinkedIn”. Widzi grafikę „Mapa”, treść
   posta i komentarz z adresem swojego linku.
2. **Rekruter** przełącza „Konkrety” i „Karuzela” (slajdy), pobiera PNG
   i PDF karuzeli; otwiera oba pliki: 1080 × 1350, stopka z domeną kariery,
   ten sam tytuł co na stronie.
3. **Rekruter** kopiuje treść posta i komentarz; adres z komentarza otwiera
   stronę oferty (ta sama, którą widzi kandydat).
4. **Delivery Lead** robi to samo na rekrutacji swojego klienta bez własnego
   linku: zakładka prosi o wygenerowanie linku i przenosi do „Link do tej
   rekrutacji”.
5. Rekrutacja bez zatwierdzonego opisu: zakładka odsyła do opisu, grafiki nie ma.

Rola, która ma nie widzieć: kandydat (publiczna trasa grafiki) — w grafice
i treści posta nie ma klienta, stawki ani nazwiska rekrutera; zamknięta
rekrutacja daje 404 grafiki.

Zmiana bez schematu bazy — backend gałęzi na wspólnej bazie stagingu.

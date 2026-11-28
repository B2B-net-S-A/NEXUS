# Scenariusz: Sprzedaż → Dzwonienie

Reguły: `docs/claude/sprzedaz/dzwonienie-kampanie-i-import-listy.md`,
`dzwonienie-lista-zmian-od-dzwoniacych-13-11.md`, `dzwonienie-lista-zmian-27-11.md`.

Kto → co robi → co widzi następny:

1. **Osoba dzwoniąca** (konto z „Sprzedaż: edycja” i własnymi rekordami kampanii, na kopii
   produkcji ok. 2700 rekordów) otwiera `/sales/calling`. Kolejka: grupy z licznikami, karta
   pierwszej pozycji, numer w trójkach.
2. Wybiera grupę (np. „Nieodebrane”): lista tylko z tej grupy, adres `?group=…`. „Kopiuj numer”
   → w schowku numer, który telefon wybierze (polski z „+48”).
3. Zapisuje wynik (np. „Nie odebrał”): karta przechodzi do następnej osoby z tej samej grupy,
   licznik „Dziś” rośnie. Id rekordu do paragonu (zapis na wspólnej bazie stagingu).
4. Tabela: numery w tym samym formacie, filtry statusu, zmiana statusu z listy.
5. **Rekruter** (bez dostępu do Sprzedaży, rola, która ma nie widzieć): `GET
   /api/sales/calling/queue` jego tokenem → 403.

Uwagi: kliknięcie terminu oferty zapisuje wynik od razu — w zrzutach „przed/po” bez zapisu
blokuj w Playwrighcie metody inne niż GET.

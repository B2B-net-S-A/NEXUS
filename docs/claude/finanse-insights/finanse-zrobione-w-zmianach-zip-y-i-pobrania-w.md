# Finanse: „Zrobione" w Zmianach, ZIP-y i pobrania w Zamówieniach PDF (0354, 23.09.2026)

Każda podzakładka „Zmian w zamówieniach" to kafelki klientów → karty zamówień
(nagłówek jak w „Zamówieniach PDF") → panel podglądu (domyślnie ukryty, Esc
zamyka). Serwis `services/order_change_checks.py`, front
`lib/finance-order-board.ts` + `components/finance/OrderChangesBoard.tsx`.

- **Odhaczenie jest AUDYTEM, nie flagą:** `order_change_checks` jest dopisywana
  (`checked`/`unchecked`), stan = ostatni wpis klucza. Bez FK (przeżywa
  usunięcie zamówienia i konta). Zapis: `POST /api/finance/order-changes/checks`
  wyłącznie Admin/Finanse (`FinanceModuleUser`), klucz musi istnieć w audycie
  miesiąca (inaczej 409), blokada doradcza na kluczu, ten sam stan = brak wpisu.
- **Klucz pozycji liczy serwer** (`item_key`): wpis dziennika `chg:ev:<id>`,
  pozycje liczone z bieżącego stanu niosą to, co je wyróżnia (`exit:`/`ending:`
  z datą końca, `gap:` ze statusem, nowe zamówienie ze stanem szkic/żywe,
  startem, a szkic także ze stawkami — dziennik celowo pomija szkice, więc
  uzupełnienie szkicu nie daje wpisu). Ponowna zmiana = nowy klucz = nowa pozycja
  „Do zrobienia"; stare odhaczenie wraca jako `superseded` („Zmieniono
  ponownie"). Zmieniając klucz, zgubisz odhaczenia z historii — nie zmieniaj.
- **Dekoracja idzie na PEŁNYM audycie, filtry dopiero po niej** — inaczej
  pozycja ukryta filtrem wyglądałaby jak zniknięte odhaczenie.
- **Badge w menu Finansów** = „Do zrobienia" podzakładki Zmiany bieżącego
  miesiąca (`GET /order-changes/summary`); pasek postępu i liczniki statusu
  liczą aktywną podzakładkę po filtrach.
- **Pobrania PDF-ów per osoba** (`order_pdf_downloads`): status „Nowy / Pobrane
  przez Ciebie" zmienia wyłącznie pobranie (plik, ZIP), nie podgląd
  (`?preview=true`) i nie odhaczenie; podmieniony plik (inna ścieżka) = znowu
  „Nowy". W „podglądzie jako" pobranie się nie zapisuje. ZIP-y:
  `GET /order-pdfs/zip` (klient / miesiąc z podfolderami / `files=`), nazwy
  `[Klient]_[NrZam]_[Nazwisko]_[Typ]_[Od]-[Do].pdf` bez polskich znaków;
  brakujący plik trafia do `BRAKUJACE_PLIKI.txt`, nie wywraca archiwum.
  „Zmiana do rozliczenia" = zamówienie ma pozycję „Do zrobienia" w audycie
  TEGO SAMEGO miesiąca.

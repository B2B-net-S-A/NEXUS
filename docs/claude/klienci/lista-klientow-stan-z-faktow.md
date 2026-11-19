# Lista „Klienci”: jeden wiersz na klienta, stan współpracy liczony z faktów (19.11.2026)
<!-- indeks: `GET /api/clients/directory/clients`, stany working/idle/archive, `ClientsList`, „Porządki portfela” `/clients/portfolio` (dawna lista zakresów), marża na liście = `list_finance_client_ids` -->

Decyzja Artura z 19.11.2026 (makiety na stagingu, wariant A ekranu 1; prywatny
artefakt w pamięci sesji, nie w repo — ma nazwy klientów i kwoty). Pytanie
Artura: „nie rozumiem, czym są aktywni klienci, klienci relacyjni, czym jest
przy nazwie klienta banner »ręcznie«”. Zakładki portfela ustawiał manifest
albo ręczne „Przenieś”, niezależnie od faktów: Tauron z dwiema otwartymi
rekrutacjami stał w „Nieaktywnych”, Nordea w dwóch zakładkach naraz (dwa
zakresy umów), a 6 z 33 „Aktywnych” nie miało nikogo.

## Stan współpracy

- **Współpracujemy** (`working`): obecny albo planowany kontrakt (aktywny lub
  w wypowiedzeniu) albo otwarta rekrutacja (`published`). Te same reguły co
  „Obecni”, „Planowani” i „otwarte rekrutacje” w profilu klienta — liczby na
  liście równają się liczbom w nagłówku profilu.
- Bez tego decyduje zakładka portfela: aktywni i relacyjni →
  **Bez bieżącej pracy** (`idle`), nieaktywni → **Archiwum** (`archive`).
- Klient z kilkoma zakresami ma **jeden** wiersz. Umowa ramowa w wierszu:
  bezterminowa wygrywa, potem najpóźniejszy koniec; pozostałe jako „+N umowy”.
- Wyszukiwanie przeszukuje wszystkie stany (stan stoi pod nazwą), liczniki
  stanów nie zależą od frazy.
- „Bez bieżącej pracy” i „Archiwum” nie mają kolumn ludzi, rekrutacji
  i marży — z definicji są tam same zera.

## Kolumny

- „Nasi ludzie” (obecni, „+N zaczyna”), „Rekrutacje” (link do Projektów
  klienta), „Marża / mc” (= „Aktywne MRR” profilu, „niepełna” przy kontrakcie
  bez stawki), „Umowa ramowa”, „Wymaga uwagi”, DL pod nazwą (w szerokiej
  tabeli własna kolumna).
- **Marża na liście wielu klientów** idzie regułą `list_finance_client_ids`
  (`api/financial_access.py`): wiersz po wierszu `can_read_client_finance`,
  a bez uprawnienia „Wyniki firmy” kwoty widzi tylko konto rządzone portfelem
  DL, u swoich klientów (decyzja z 02.11.2026). Tej samej reguły używa
  „Moi klienci”. Nie dokładaj trzeciej kopii.
- **„Wymaga uwagi”**: umowa wygasła albo kończy się w 90 dni, potem
  konsultanci (te same znaczniki co podzakładka „Wymaga uwagi” w zakładce
  Konsultanci, liczone serwerem z `consultant_order_state`, tylko u obecnych:
  „N zamówień bez kontynuacji”, „Brak bieżącego zamówienia”, „N umów
  wypowiedzianych”), potem raport miesiąca i relacja bez kontaktu.
- **Nie wstawiaj do „Wymaga uwagi” liczby „po terminie” z rozliczenia
  klienta**, dopóki NEXUS nie zapisuje zapłat: 19.11.2026 żadna z 2 741 faktur
  „po terminie” nie miała daty zapłaty, więc liczba nie mówi o zaległościach.

## „Porządki portfela” (`/clients/portfolio`)

- Dawna lista zakresów (`ClientsListV2 variant="portfolio"`, `GET
  /api/clients/directory` bez zmian): zakładki portfela z manifestu,
  „Przenieś”, ręczne daty umowy (plakietka „ręcznie”), „Status klienta”,
  czyszczenie nieaktywnych. Wejście: link pod listą „Klienci” dla
  `client.portfolio.manage`.
- Zakładka portfela nadal decyduje o „Bez bieżącej pracy” / „Archiwum”
  i o tym, czy klienta da się wybrać w Rekrutacjach i Kontraktach.

## Adresy i harness

- `/clients?state=working|idle|archive&q=&page=`; dawne `?category=` i `?view=`
  otwierają listę i znikają z adresu. Klucz zapytania
  `["clients-directory", "clients", stan, fraza, strona, moi]` — wspólny
  prefiks `clients-directory` odświeża listę po dodaniu klienta.
- Eksport: `GET /api/clients/directory/clients/export` (to, co widać, bez stron).
- Harness `/preview/clients-list` (nowa lista) i
  `/preview/clients-list?harness=portfolio` („Porządki portfela”).
- Testy: `backend/tests/test_client_directory.py` (sekcja „Lista »Klienci«”),
  `frontend/src/components/clients/__tests__/ClientsList.test.tsx`.

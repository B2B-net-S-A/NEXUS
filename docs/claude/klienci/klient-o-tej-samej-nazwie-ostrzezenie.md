# Klient o tej samej nazwie — ostrzeżenie przy dodawaniu (22.10.2026)

<!-- indeks: 409 `client_duplicate_warning`, `acknowledge_duplicate`, „Dodaj mimo to”, `normalize_company_name` -->

12.10.2026 w zakładce Aktywni dodano klienta „Energa”, choć stary rekord
(z rekrutacjami, procesami i regułami CV) leżał w Nieaktywnych. Lista
pokazywała Energę w obu zakładkach. 22.10.2026 pusty duplikat został scalony
w stary rekord, a stary przeniesiony do Aktywnych.

- `POST /api/clients` odpowiada 409 `client_duplicate_warning`, gdy widoczny
  klient to ta sama firma: `services/client_duplicates.py`. Treść niesie listę
  klientów z zakładkami (`categories`), żeby było wiadomo, gdzie szukać.
- **Ostrzeżenie, nie blokada.** Ta sama nazwa bywa inną firmą. Okno „Dodaj
  firmę” pokazuje ramkę `ExistingClientNotice` z „Otwórz profil” i „Dodaj mimo
  to”, które wysyła `acknowledge_duplicate=true`.
- „Ta sama firma” = `normalize_company_name` (reguła wspólna z ATLAS-em: bez
  wielkości liter, znaków diakrytycznych i formy prawnej) na nazwie źródłowej,
  wyświetlanej, prawnej i aktywnych aliasach. Wspólny początek nazwy
  („Energa Obrót”) to nie ta sama firma.
- Porównujemy tylko widocznych klientów (`visible_client_predicates`):
  scalony, ukryty albo usunięty rekord nie jest „już w bazie” dla osoby,
  która go nie widzi.

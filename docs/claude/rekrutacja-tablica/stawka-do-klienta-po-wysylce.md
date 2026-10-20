# Zmiana stawki do klienta po wysyłce CV (20.10.2026)

Delivery Lead zgłosił: „jak już wyślę, to nie można zmienić”. Poprawka działała
tylko w profilu kandydata (Rekrutacje → „Edytuj”), a panel osoby pokazywał
kwotę bez akcji. Decyzje Artura 20.10.2026 (makiety
https://claude.ai/artifact/DdW4ScU6PYWiLwssZfYJr8): wariant A, blokada po
zamówieniu, zapis jak dotąd. Kod: `services/client_rate_correction.py`,
`PATCH`/`GET …/recruitments/{job_id}/client-rate[/history]` w
`api/candidates.py`, front `components/v2/rate-change/ClientRateChangeDialog.tsx`,
`lib/api/clientRateHistory.ts`.

- **„Zmień” przy „Do klienta” w panelu osoby** i „Edytuj” istniejącej kwoty
  w profilu otwierają to samo okno: wysłane za ile, kiedy i przez kogo; nowa
  kwota z podglądem marży; powód (wymagany: klient wynegocjował / pomyłka przy
  wysyłce / inny) i notatka. Pierwszy wpis stawki („Uzupełnij”) zostaje
  w polu, bez okna.
- **Zapisuje tylko uprawnienie „wysyłka CV do klienta”** (DL i admin,
  `resolve_client_rate_write`) — bez zmian. Historię czytają role ze stawką do
  klienta (`user_can_view_client_rate`); rekruter dostaje 403.
- **Po zamówieniu stawki nie zmienia się w rekrutacji** (`order_lock`):
  zamówienie pary bez anulowanych — `client_orders.job_id` tej rekrutacji albo,
  przy starym zamówieniu bez `job_id`, kontrakt z `contracts.job_id`. `PATCH`
  zwraca 409, okno i profil odsyłają do kontraktu z zamówieniem. Dotyczy też
  zwykłego „Edytuj” w profilu.
- **Bez nowej tabeli.** Powód to kod w audycie `client_rate_changed`
  (`details.reason`), słowa DL-a — notatka `dl_rate` (`external_source =
  client_rate_change`, `details.note_id`), więc rekruter widzi zdanie
  zastępcze. Audyt nie niesie wolnego tekstu (zasada `candidate_audit`).
- **„Stara” kwota w audycie to stawka PARY sprzed zmiany**, nie wiersza:
  ruch na kolejny etap zaczyna wiersz bez stawki, więc po „Rozmowie” stara
  kwota z samego wiersza byłaby pusta.
- **Historia:** kwota wysyłki = „stara” kwota pierwszej zmiany po pierwszym
  wierszu „CV wysłane” (wiersz mógł zostać nadpisany), bez zmian — bieżąca
  stawka. Zmiany sprzed wysyłki nie są historią po wysyłce.
- **Zmiana stawki KANDYDATA to osobna sprawa** (`change_rate`, plik
  `screening-notatki/zmiana-stawki-kandydata-w-trakcie-procesu.md`) — okno
  mówi to wprost.

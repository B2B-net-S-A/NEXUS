# Umowy ramowe idą za scaleniem klienta (16.11.2026)

<!-- indeks: merge-into przenosi umowy, korekta 0721, inwariant manifestu uznaje umowę na celu scalenia -->

Umowy z manifestu portfela (`client_excel`) leżały na rekordach `portfolio:*`
scalonych w klientów z Traffita (Credit Agricole, Ergo, Nationale, BNP CIB,
Alior) i na dwóch duplikatach bez flagi (Santander → ERSTE, NBP). Karta
klienta, wyszukiwanie umów (Jarvis), katalog raportów, „Moi klienci” i wybór
umowy w zamówieniach czytają umowy po `client_id` klienta, więc ich nie było.

- **Decyzja Artura: przenieść dane, nie czytać po `merged_into_client_id`.**
  Jedno miejsce zamiast kilkunastu odczytów, a nowy ekran nie musi pamiętać
  o duplikatach.
- **Scalenie przenosi umowy ramowe** (`_move_client_materials_on_merge`).
  Aneksy i fragmenty treści idą za umową kluczem obcym. Punkty w Qdrancie
  niosą tylko id umowy (id punktu = id fragmentu), więc wektorów się nie
  odbudowuje. Część umowy CeZ zajęta u celu zostaje na duplikacie.
- **Wiersz importu i zakres portfela zostają na duplikacie**, jak w
  `scalenie-cardif-pelne-przeniesienie-danych.md`. Inwariant
  `live_framework_contracts` w `/api/health/deep` uznaje umowę na
  `merged_into_client_id` klienta wiersza i przeniesienia z
  `TICKET_MOVES` (`app/services/framework_contract_owner_repair.py`).
  Każde inne przesunięcie umowy z manifestu nadal jest dryfem i daje 503.
- **Korekta `0721_framework_contract_owner_repair`** (blok
  `repair-framework-contract-owner` w `entrypoint.sh`) przepięła 7 umów
  i usunęła ręcznie wgraną drugą kopię umowy Aliora, która miała ten sam plik.
  Paragon to wyłącznie ID. Cofnięcie przenosi umowę z powrotem według
  `moves` w paragonie. Wtedy trzeba też zdjąć parę z `TICKET_MOVES`,
  inaczej health jej nie rozpozna.
- **Kolejny duplikat z umową:** najpierw scalenie przez API, bo samo przenosi
  umowy. Duplikat bez flagi scalenia dostaje wpis w `TICKET_MOVES` i własny marker.

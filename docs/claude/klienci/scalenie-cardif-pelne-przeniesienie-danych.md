# Pełne scalenie klienta-duplikatu: BNP Paribas Cardif (52) → Cardif Assurances (38335) (13.10.2026)

<!-- indeks: `cardif_client_merge_repair`, najpierw dane, potem flaga; wzór na duplikaty -->

Rekord 52 powstał z mapowania w Traffit i trzy razy ściągnął na siebie dane
właściwego klienta (dwa zgłoszenia z sierpnia → migracja 0244, potem umowa
1520/2026). Korekta `app/services/cardif_client_merge_repair.py` (blok
`repair-cardif-client-merge` w `entrypoint.sh`, paragon
`app_settings['0435_cardif_client_merge']`) przeniosła resztę i zamknęła rekord.

- **Najpierw dane, potem flaga.** `POST /api/clients/{id}/merge-into/{target}`
  przenosi tylko materiały (kontakty, wiedzę, kartę) i chowa rekord — rekrutacje,
  kontrakty i umowy zostałyby na niewidocznym wierszu. Duplikat z historią
  wymaga więc korekty: rekrutacje z procesami wprost, kontrakty przez
  `contract_client_reassign`, materiały przez `_move_client_materials_on_merge`,
  alerty DL razem z linkiem, a po zmianie klienta rekrutacji
  `record_bulk_reindex` (payload wektora niesie `client_id`).
- **Flaga scalenia tylko na pustym rekordzie:** `merged_into_client_id`
  i `archived_at` stają dopiero, gdy `assess_client_merge_blockers` nic nie
  zwraca **i** paragon nie ma `unexpected_references`. Kontrakt z blokerem
  przepięcia albo umowa z niespełnioną bramką zostają na duplikacie, a flaga
  czeka na człowieka.
- **Na duplikacie zostaje wpis katalogu:** zakres portfela, wiersz importu
  i przydział DL (ruszenie zakresu psuje inwariant manifestu w
  `/api/health/deep`), oraz dziennik — `critical_events` i historia rekordu
  nie są przepisywane.
- **Umowa z Generatora:** powiązanie z kontraktem idzie tą samą funkcją co
  przycisk „Powiąż z kontraktem” (`apply_contract_link`). Zmienia się klient
  wiersza i kolumna `client_name` (rejestr, przyszłe aneksy); `render_payload`
  to treść podpisanego dokumentu i zostaje. Korekta nie dołącza DOCX do
  dokumentów kontraktu — byłby to odtworzony, niepodpisany plik, który
  synchronizacja wysłałaby do SharePointa. Rekrutację i numer umowy kontrakt
  #689 dostał drugim biegiem (`0436_cardif_contract_fill`), bo pierwszy
  powiązał umowę, zanim powiązanie zaczęło uzupełniać kontrakt.
- **Rekord 52 jest nagrobkiem.** Zgłoszenie prosiło o pusty, widoczny rekord;
  decyzją z 13.10.2026 jest oznaczony jako scalony, bo widoczny duplikat dawał
  się dalej wybrać, a pięć rekrutacji bez „Prowadzona w NEXUSIE” wróciłoby na
  niego przy ostatnim imporcie z Traffita. Nie zdejmuj flagi i nie czyść
  `external_id` — to on kieruje import na klienta 38335.
- **Kolejny duplikat tego typu:** ten sam wzór (dataclass z id i tokenem nazwy
  jako kontrolą zaszytych id, bramki z kodem pominięcia, marker + blokada
  doradcza), nie surowy SQL w migracji jak w 0244.

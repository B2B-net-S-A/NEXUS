# Scalenie duplikatu PFRON 58469 → 122 (19.11.2026)

<!-- indeks: `run_repair_pfron_client_merge`, Rada „Placementy według klienta”, korekta ręczna, nie krok startu -->

Na `/rada?tab=firma` ten sam klient stał w „Placementy według klienta” dwa razy
(„PFRON” i pełna nazwa). Przyczyna: dwa rekordy `clients`. 122 (Traffit, 23 kontrakty,
32 rekrutacje, 34 zamówienia, nazwa wyświetlana pełna) i 58469 (ręczny z 02.09.2026,
nieaktywny, bez kontraktów, 4 zamknięte rekrutacje z jednym placementem, 1 kontakt).
Rada bierze nazwę z klienta rekrutacji, a lista kontraktorów z klienta kontraktu.

- **Zostaje 122** (decyzja Artura 19.11.2026): ma historię, import z Traffita i stałą w kodzie.
- **Przycisk „Scal” nie wystarcza.** `merge-into` przenosi materiały (kontakty, kartę,
  umowy ramowe) i chowa rekord, ale rekrutacje zostają na ukrytym wierszu — Rada
  nadal liczyłaby dwa wiersze. Dlatego korekta `scripts/repairs/run_repair_pfron_client_merge.py`
  używa logiki scalenia Cardifa (`cardif_client_merge_repair.py`): rekrutacje z procesami
  (z `record_bulk_reindex`), kontakty, materiały i alerty DL na 122, potem flaga scalenia.
- **Ręcznie, po zgodzie Artura**, nie z `entrypoint.sh` (wdrożenie uruchomiłoby ją bez
  zgody): `python -m scripts.repairs.run_repair_pfron_client_merge` w kontenerze backendu.
  Znacznik `0738_pfron_client_merge` w `app_settings`, drugi bieg nic nie zmienia.
  Kontrola tożsamości: nazwy obu rekordów zawierają „pfron”, inaczej korekta pomija krok.
- Zakres portfela 58469 zostaje na duplikacie (inwariant manifestu w `/api/health/deep`).
- Po biegu: `/rada?tab=firma` pokazuje PFRON raz (2 placementy łącznie w oknie, jeśli oba mieszczą się w oknie).

## Drugi krok (19.11.2026)

Pierwszy bieg przepiął rekrutacje, kontakt i alerty, ale zatrzymał się przed flagą scalenia:
na 58469 zostało 11 wygenerowanych CV i 1 dokument poczty zamówień. Pierwszą próbę
(ta sama zmienna `PFRON_ORDER_EXTRACTION_CLIENT_IDS=58469`) korekta zapisała jako znacznik
`skipped`, który zablokował ponowienie — dlatego znacznik skasowano ręcznie, a drugi krok
(`run_repair_pfron_client_merge_documents`, znacznik `0738_pfron_client_merge_documents`)
nie zapisuje znacznika, gdy bieg został pominięty. Uruchomienie ręczne, po zgodzie Artura.

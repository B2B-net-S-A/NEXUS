# Nowy profil na adres z nagrobka: automat stop, okno pyta, samo zgłoszenie ze śladem (03.11.2026)
<!-- indeks: nagrobek po mailu przy zakładaniu profilu, candidate_erased, confirm_erased, recreated_after_erasure -->

Trwałe usunięcie stawia nagrobek adresu (`purged_candidates`, `candidate_email_tombstone`).
Do 03.11.2026 czytały go tylko importy i API v1, więc profil usuniętej osoby mógł
wrócić z poczty, okna albo importu bez żadnego sygnału dla rekrutera. Decyzja Artura z 03.11.2026:

| Droga | Plik | Zachowanie na adres z nagrobka |
|---|---|---|
| Poczta M365 | `services/m365/attachment_handler.py` | Bez profilu, `parse_error = candidate_erased`, załącznik wypada z kolejki |
| Import CSV i `/bulk-import` | `api/import_export.py`, `api/candidates.py` | Wiersz pominięty z powodem |
| Okno ręczne, okna z CV | `POST /api/candidates`, `/from-cv` | 409 `candidate_erased`, okno pyta, zgoda wraca z `confirm_erased=true` |
| Masowy import CV | `BulkImportCVsV2.tsx` | Plik pominięty ze zdaniem serwera, bez pytania |
| „Utwórz kandydata” w Zgłoszeniach | `api/application_submissions.py` | Jak okno, zgoda w polu `confirm_erased` |
| Link, strona kariery | `services/public_apply.py` | Przechodzi, wpis w historii i zdanie w dzwonku |
| Scraper portali | `/from-cv` z `is_integration_request` | Przechodzi, wpis w historii |
| API v1, Traffit, Talent Radar | jak dotąd | 409 albo pominięty wiersz |

- **Ślad:** `Activity.action = recreated_after_erasure`, `details.via` = `screen` albo
  `self_application`. Bez danych osoby.
- **`force` nie pomija pytania**, bo dotyczy duplikatów, a nie nagrobka.
- **Nagrobek nie dowodzi prośby osoby.** Stawia go każde trwałe usunięcie, także
  duplikatu, dlatego tekst na ekranie mówi o usuniętym profilu. 6 z 12 trwałych usunięć
  sprzed 20.10.2026 nagrobka nie ma i adresów już się nie odtworzy.
- **Zostaje poza nagrobkiem:** wtyczka LinkedIn (profil bez adresu, decyzja Artura
  z 03.11.2026: sam e-mail wystarczy), zamówienie z maila i seed e-Zdrowie (sama nazwa)
  oraz CV bez adresu. Zapis adresu na istniejący profil też nagrobka nie czyta.
- **Czarna lista to status profilu**, więc znika razem z nim przy „Usuń profil”.
  Osoba, która ma być zablokowana, zostaje na czarnej liście.
- Usunięcie nadal nie kasuje CV (decyzja z 26.09.2026,
  `uprawnienia/integralnosc-i-uprawnienia-reguly-po-audytach.md`).

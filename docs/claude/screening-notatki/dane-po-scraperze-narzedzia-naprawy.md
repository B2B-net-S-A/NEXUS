# Dane po scraperze — narzędzia naprawy (06.10.2026)

Audyt `docs/audits/2026-10-06/rekrutacja-przekazanie-i-wyszukiwanie.md` (D4, D5).
Oba narzędzia: admin, próba `dry_run=true` niczego nie zmienia (liczby + przykłady
z samymi ID), zapis wymaga `expected=` = liczbie z próby (409 przy rozjeździe
i przy pustym planie), paragon = liczby i ID, kwoty pod `repair_details_…`.

- **Karty scrapera** — `POST /api/admin/proposals/convert-integration-cards`
  (`mode=convert|delete`, sekcja „Notatki: przypięcie…” wyżej). Wynik w notatce
  automatu bywa HTML-em (`score:&nbsp;71`) — wzorzec SQL go łapie.
- **Stawki od scrapera** — `POST /api/admin/candidates/scraper-rates/revert`
  (`services/scraper_rate_revert.py`). Bierze zapisy `profile_rate_changed`
  ze źródłem `manual` od użytkowników serwisowych klientów OAuth, tylko gdy
  wersja stawki profilu nadal jest wersją z zapisu scrapera (człowiek później =
  zostaje). Przywraca stawkę sprzed scrapera z datą POPRZEDNIEJ stawki
  (`write_profile_rate(rate_updated_at=…)`), zdejmuje `_manual_override_rate`
  (chyba że wcześniej pisał człowiek), wyłącza każdy zapis scrapera z „Stawki
  od” (`candidate_rate_decisions`, klucz `profile:{activity_id}`). Stawka
  sprzed scrapera w walucie innej niż PLN zostaje (`non_pln_previous`), zapis
  idzie paczkami po 200 z commitem i paragonem na paczkę. Wpis w
  dzienniku: `profile_rate_scraper_reverted`. Nocny odczyt notatek wycina linię
  „szacunek stawki B2B …” (`notes_insights_extractor.strip_scraper_rate_estimate`).
- **Runy integracji wiszące w `running` > 6 h** zamyka pętla alertów zastoju
  (`integration_runs.close_stuck_runs` → `failed`).
- **Job JJIT w NEXUSIE (`services/integrations/jjit/`, dziś `dry_run`)** nie ma
  sita `check-duplicates` ani ponowień przy 503, które ma scraper na Macu —
  przed przełączeniem go na zapis trzeba je dołożyć.

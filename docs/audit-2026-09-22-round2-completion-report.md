# Naprawa audytu NEXUS z 22.09.2026 — druga runda

Źródło ustaleń: raport audytu (11 obszarów) https://claude.ai/artifact/E5hzhpxZDVF5zC571WBtM7
oraz kontrola naprawy audytu Codexa (#1700). Plan: jeden PR, migracja `0351_audit_round2`.

## Status ustaleń

| Obszar | ID | Status |
|---|---|---|
| Bezpieczeństwo | SEC-01 (DOCX kradnie token), SEC-01b (CSP) | naprawione |
| | SEC-02 (SECRET_KEY z historii) | ostrzeżenie w logach; **rotacja — decyzja Artura** |
| | SEC-03/CAND-03 (upload do RAM), SEC-05, SEC-06, SEC-07, AI-01, AI-03, FE-N01, PROD-08 | naprawione |
| | SEC-04 (egzekwowanie zakresów OAuth) | operacja: włączyć flagę po 7 dniach bez `would_deny` |
| Poprawki #1700 | FIX-01 (regresja OAuth), FIX-02..10, FIX-12 | naprawione; FIX-01 węziej: blokada dla klientów bez `*:write` |
| | FIX-11 | pominięte (decyzja: zostaje reguła INT-08) |
| AI | AI-02, AI-04..07 | naprawione |
| Traffit/automaty/dane | INTG-01..05, DATA-01..05, REC-01, PROD-01, PROD-02, PROD-10 | naprawione (kod); dane — operacje niżej |
| Statystyki | STAT-01..04 | naprawione wcześniej w #1714 |
| Pieniądze | FIN-01, FIN-02 (+FE-N02), FIN-03, FIN-MD-01..08 | naprawione |
| Poczta zamówień | FIN-MAIL-01..09, FE-N03 | naprawione |
| Finanse → Zmiany | FIN-CHG-1..7 | naprawione |
| Kandydaci/rekrutacje/UI | CAND-01/02/04/05/06/07, REC-02..07, FE-N05..N10 | naprawione; FE-N04 zrobione wcześniej (#1719) |
| CI/deploy | OPS-N01..N08, PROD-04 (okno ciszy) | naprawione; E2E zielone od #1717 |
| Operacje | PROD-05, PROD-07, PROD-09, PROD-11, PROD-12 | poza kodem — lista niżej |

## Odstępstwa od planu (świadome)

- **FIX-01:** POST „tylko do odczytu” blokowany zawsze tylko dla klientów bez żadnego `*:write` — dokładny stan sprzed #1700; szersza blokada mogłaby zatrzymać działające integracje.
- **Limit ciała żądania 30 MB**, wyjątek `/api/cv-generator/generate-upload` 101 MB (dwa pliki po 50 MB).
- **CSP Report-Only** dopuszcza `https:` w `img-src` i Google Fonts (realne źródła), żeby raporty nie były szumem.
- **SEC-06:** aktywność właściciela linku sprawdzana przy każdym odczycie (pokrywa każdą ścieżkę dezaktywacji i odwraca się po przywróceniu konta); trwałe unieważnienie tylko przy usunięciu konta.
- **PROD-02:** snapshot to kopia w storage `stage-cv/<candidate_id>/<sha256>`, nie wskaźnik na plik kandydata — snapshot ma być niemutowalny, a klucz per kandydat pozwala skasować obiekty przy art. 17.
- **INTG-05:** reconciler kolejkuje rekrutację tylko bez intencji w toku (brak deduplikacji w `record_bulk_reindex`).
- **FIN-MD-02:** automatyczna korekta tylko dla zamian ze znacznikiem `auto_rebalance` (zapisanych od wdrożenia) — historyczne budżety mogły być już rozliczone z klientem.
- **FIN-MAIL-06:** `existing_person_ids` czyszczone tylko dla TCM; DL potrzebuje podpowiedzi „osoba jest w bazie”.
- **FIN-MAIL-07:** powrót po przerwie bez imiennika pozostaje automatyczny (decyzja z 10.09).
- **Deploy:** poranny `schedule` to `15 5,6 * * *` (w zimie 05:15 UTC jest jeszcze w oknie).

## Zmiany zachowania widoczne dla ludzi

- Usunięcie jedynego zamówienia z umowy zostawia umowę bez przychodu (okno usuwania to mówi).
- Poczta zamówień: więcej wpisów w kolejce u BIK, Polkomtela, BNP, PFRON i Credit Agricole (okres musi potwierdzić reguła) i przy walucie innej niż PLN.
- Pierwszy przebieg skanera domknie historyczne linie MD zakończone „w przód” (zmiana Zejść/Braków w bieżącym miesiącu).
- Nocny przegląd bazy: najwyżej 5 rekrutacji na noc, surowe wyniki automatycznych przeglądów żyją 2 dni.
- Deploye automatyczne czekają na okno ciszy 0–7 czasu polskiego; „Coolify set env” domyślnie nie wdraża.
- Link alertu SLA prowadzi do `/dashboard?panel=nadzor-kontaktu`.

## Operacje poza PR (Artur / operator)

1. Przed merge'em: katalog `/var/lib/nexus-status` + cron co 15 min zapisujący `backup-volume.json` (`used_percent`, `avail_gb`, `checked_at`, zapis przez plik tymczasowy i `mv`).
2. PROD-05: wyłączyć cron hosta `/root/scripts/traffit-delta-sync.sh`.
3. Po deployu, w nocy: `POST /api/admin/traffit/sync?mode=full&phases=jobs,pipelines` (korekta +2 h w `moved_at`); w `/sync/status` sprawdzić `pipelines.skipped_before_since > 0` przy delcie.
4. PROD-02: `docker exec <backend> python -m app.cli.stage_cv_snapshot_offload` (sucho → `--apply`), potem `VACUUM FULL candidate_stage_cvs` w oknie serwisowym.
5. Kopie poza serwerem: klucze B2 + age → `BACKUP_ENABLED=true`, sekrety drillu, `BACKUP_MONITORING_ENABLED=true`; `KEEP_PG=14` w `/root/nexus-backup.sh`.
6. Automaty: po kroku 4 jednorazowo zgłosić rekrutacje opublikowane od 17.09; obserwować `auto_runs_estimated_bytes`.
7. OAuth: po 7 dniach bez `would_deny` → `OAUTH_ROUTE_SCOPES_ENFORCE=true`; sprawdzić zakres `QUEUE_BOT_TOKEN` (`dequeuePullRequest`).
8. SECRET_KEY: rotacja w wybranym oknie (wyloguje wszystkich); log strażnika zniknie.
9. PROD-09: `DROP TABLE users_cleanup_backup_2026_05_18`.
10. GitHub: środowisko Production z polityką `main` + recenzent; secret scanning/push protection (płatne); „E2E stack (ci-chromium)” do rulesetu 22799346.
11. PROD-04: przy deployu sprawdzić (`docker events`), czy Postgres/Qdrant są odtwarzane.
12. PROD-11: po tygodniu zmierzyć wywołania `cv_parser`/h.
13. PROD-12: `/api/admin/index-cleanup`; ręczny przegląd duplikatów e-maili i 2 osób z nagrobkiem Traffita.
14. Po wdrożeniu przejrzeć raporty CSP w Sentry i pierwsze wywołania OpenAI ze `strict: true`.

## Weryfikacja

- Backend: testy obszarów uruchomione na zmigrowanym Postgresie (0351) przez 7 wykonawców — łącznie ok. 3,8 tys. testów zielonych; pełny bieg przez `gh workflow run CI` na gałęzi.
- Frontend: `tsc --noEmit` bez błędów, lint bez błędów, pełny vitest.
- Instrukcja zamówień w Pomocy zaktualizowana i ostemplowana.

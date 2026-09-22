# Naprawa audytu NEXUS z 22.09.2026

Źródło: [audyt-nexus-2026-09-22.md](audyt-nexus-2026-09-22.md) (48 ustaleń + aneks INT-13).

## Weryfikacja przed naprawą

Wszystkie 48 ustaleń sprawdzono na `main` 4920ee1 (o 13 commitów nowszym niż wersja audytowana).

**Wynik:** żadne ustalenie nie było fałszywe ani wcześniej naprawione. Pięć jest opisanych nieprecyzyjnie:

| ID | Na czym polega nieprecyzyjność |
|---|---|
| CAL-01 | Prawdziwy jest tylko wariant ze zmianą rekrutacji. Daty były sprawdzane przed wysłaniem zmiany do Outlooka. |
| AUTH-02 | Token żyje godzinę. |
| SIG-05 | Błąd dotyczy tylko tekstu. |
| AN-02 | Endpoint `reports/sales` nie ma konsumenta. |
| SCV-02 | Błąd występuje tylko przy lokalizacji z krajem. |

**Stan produkcji w chwili naprawy** (odczyt tylko do odczytu):

| Obszar | Stan |
|---|---|
| Poczta aplikacji | `m365_mail`: 91 błędów 403 z rzędu |
| Klienci OAuth | 2 aktywni, używani codziennie: ATLAS `candidate:read` oraz scrapery `candidate:write, job:write` |
| Moduł podpisu | `SIGNING_ENABLED=true`, 0 podpisów w historii |
| Rekrutacje | 326 opublikowanych |
| Maile z NEXUSA | oba kiedykolwiek wysłane mają duplikat w bazie |
| Testy E2E | czerwone na każdym merge'u |
| Próba odtworzenia z kopii (backup drill) | czerwona 4 tygodnie z rzędu |

## Status ustaleń

| ID | Status | Poprawka / test |
|---|---|---|
| OPS-01 | naprawione w kodzie; wymaganie zielonego E2E przed merge'em (ruleset) — po zielonym E2E | `VirtualTable` pusty stan jako wiersz siatki, min. szerokość nazwiska w `PeopleTable`, test tablicy pokazuje puste kolumny |
| OPS-02 | **właściciel** | konto E2E na liście break-glass, potem `E2E_POST_DEPLOY_ENABLED=true` |
| OPS-03 | **właściciel** | sekrety `BACKUP_AGE_PRIVATE_KEY`, `BACKUP_S3_*` + kopia poza serwerem |
| OPS-04 | **właściciel (Entra)** | uprawnienie `Mail.Send` (aplikacyjne) + nadawca w zakresie Application Access Policy; potem `M365_MAIL_SENDER_UPN` |
| AUTH-01 | naprawione (tryb cienia) | `services/oauth_route_scopes.py`, flaga `OAUTH_ROUTE_SCOPES_ENFORCE`; `test_oauth_client_acting_user.py` |
| AUTH-02 | naprawione | przecięcie z `client.scopes`; `require_scope` czyta klienta z bazy |
| AUTH-03 | naprawione | 403 `password_change_required` dla tokenu z `fpc` |
| AUTH-04 | naprawione | 400 dla konta bez hasła, `has_password` w `/auth/me` |
| SIG-01…05 | naprawione + moduł wyłączony (`SIGNING_ENABLED=false`) | `test_signing_finalize_integrity.py`; `upload-signed` usunięty |
| CAL-01 | naprawione | walidacja przed wysłaniem zmiany do Outlooka; `test_calendar_outlook_update.py` |
| CV-01 | naprawione | GET bez zapisu, `finalize`/`review` przyjmują `none` |
| INT-04/05/07 | naprawione | rezerwacja wiersza przed wywołaniem Graph, `send_state` (migracja 0341), `client_request_id`; `test_m365_send_once.py` |
| INT-06 | naprawione | brak ponowień POST po timeoucie, `transactionId` |
| INT-08 | naprawione | błąd listowania załączników zatrzymuje kursor, ponowienia `download_failed[n]`; `test_m365_attachment_retry.py` |
| INT-14 | naprawione | dopasowanie po `internetMessageId` + jednorazowe usunięcie duplikatów (`0341_m365_email_dedupe`); `test_m365_email_identity.py` |
| INT-01…03 | naprawione (moduł wyłączony) | `services/cloudtalk_candidate.py`; `test_audit_cloudtalk_sync_int.py` |
| INT-09/10 | naprawione (moduł wyłączony) | `services/autenti/activity_log.py`; `test_audit_autenti_int.py` |
| INT-11…13 | naprawione | paginacja, `DateTime`, znacznik ostatniej synchronizacji przesuwany tylko przy braku błędów; dodatkowo naprawiony zapis notatek (ON CONFLICT); `test_audit_fireflies_sync_int.py` |
| AN-01/02 | naprawione | stawki z harmonogramów na dzień, pomijanie kontraktów jeszcze nierozpoczętych, prognoza per miesiąc |
| AN-03 | naprawione | 422 dla przyszłej zmiany jednostki/godzin |
| SCV-01 | naprawione | `_canon_skill` rozróżnia C/C++/C#/F#/.NET; podbite wersje scoringu i bramki wymagań |
| SCV-02 | naprawione | `location_utils.city_tokens` |
| SCV-03 | naprawione (interaktywne CV wyłączone) | `build_requirements` z `requirements_for_job` |
| SCV-04 | naprawione | wartości nieskończone i spoza zakresu → `skipped_rows` |
| FE-01…13 | naprawione | patrz commity `fix(ui)` i `fix(finanse)` |

## Zmiany zachowania, o których warto wiedzieć

**Analityka i import**
- Kwoty w analityce kontraktów są liczone w pełnych złotych, tak jak na pozostałych ekranach.
- Prognoza obejmuje także kontrakty bez daty startu.
- Import MD odrzuca ujemne MD.

**Poczta M365**
- Sync łączy kopię maila wysłanego do siebie (Wysłane + Odebrane) w jeden wiersz.

**Moduł podpisu** (dotyczy ponownego włączenia)
- Sprawy sprzed zmiany wymagają ponownego pobrania PDF przez konsultanta.
- `SIGNING_COMPANY_SIGNER_NAMES` jest puste.

**Zmiana hasła**
- Użytkownik z wymuszoną zmianą hasła dostaje 403 na zapytania w tle, dopóki nie zmieni hasła.

## Po wdrożeniu

1. `/api/health` pokazuje nowy SHA, `/api/health/alembic` nie pokazuje dryfu, a paragon `0341_m365_email_dedupe` jest w `app_settings`.
2. Logi WARNING z trybu cienia OAuth przez tydzień. Brakujące trasy dopisać do mapy, potem ustawić `OAUTH_ROUTE_SCOPES_ENFORCE=true`.
3. `scripts/eval_matching.py`: porównanie przed i po SCV-01/02 (Precision@5, MRR).
4. Po zielonym E2E dodać „E2E stack (ci-chromium)” do rulesetu 22799346.

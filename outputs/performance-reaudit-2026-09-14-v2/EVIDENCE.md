# Dowody — drugi reaudyt NEXUS 14.09.2026

[Raport](../../docs/performance-and-availability-reaudit-2026-09-14-v2.md). Badany i ostatecznie wdrożony SHA: `a30d915c5e52c2adfb7e18af24de643f7bf3347f`. Baseline: `2c00f7cb9eb39bbe8b11271f61685ac0a91c8b8d`. Nie nadpisywano materiałów pierwszego reaudytu.

## Incydent podczas wdrożenia

[probe-series.json](probe-series.json): 42 pary lekkich GET-ów do frontend `/login` i API `/api/health/live`, bez autoryzacji i bez danych biznesowych. 18 par w pierwszej serii, 24 w kontynuacji; normalnie około 5 s odstępu między parami, jedna dłuższa przerwa między seriami. Nagłówki wybrane wyłącznie diagnostycznie; body zapisane dla health i błędów. Zegary UTC.

[incident-summary.json](incident-summary.json) wylicza statusy oraz czas pierwszej/ostatniej błędnej i sąsiadujących dobrych próbek. 17 błędów FE503; 11 błędów API (3×502,8×503). Błędy nie są timeoutami generatora: zawierają rzeczywiste odpowiedzi HTTP. Nie jest to test pojemności ani procent uptime miesięcznego.

[Deploy #1509](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34837102543): istniejące wdrożenie zaczęło się 11:13:20 UTC, sukces, ostatni deep health 11:18:48 UTC. [Metadata joba](deploy-1509.json). Audytor nie uruchamiał tego deployu. Poprzedni SHA widziany przez sondę: 934aef8f; następny: a30d915c. FE i API wróciły do 200. [final-health.json](final-health.json): health/deep/Alembic po przełączeniu.

## Kod i testy

- [pr-1507.json](pr-1507.json) oraz [pr-1509.json](pr-1509.json): SHA i statusCheckRollup.
- [existing-frontend-tests.json](existing-frontend-tests.json):29 testów PASS (5 plików).
- [insights-contract-tests.json](insights-contract-tests.json):15 testów PASS. Łącznie 44 istniejące testy frontend.
- [frontend-reaudit.test.tsx](frontend-reaudit.test.tsx), [konfiguracja](frontend-vitest.config.mts), [frontend-repro-results.json](frontend-repro-results.json):7 niezależnych testów zachowania. Rzeczywiste moduły bieżącego snapshotu; syntetyczne adaptery HTTP, WS, zegar, odbiorca Sentry. Bez wysyłania requestów i zdarzeń do usług. PASS testu braku Retry-After jest charakterystyką aktualnej polityki, nie jej naprawą.
- Backend: `PYTHONPATH=backend python3 -m pytest --noconftest -q backend/tests/test_core_cache_single_flight.py backend/tests/test_entrypoint_document_kind_guard.py` w snapshotcie → 6 PASS (0,22s).
- [backend-repro.py](backend-repro.py), [wyniki](backend-repro-results.json): oryginalne funkcje z AST/module; cancellation w nowym await zostawia refcount; prawdziwa AsyncSession w lokalnym SQLite potwierdza zachowanie po flush; czysty read oddaje połączenie; bounded read odrzuca oversized po limit+1.
- [hor-repro.py](hor-repro.py), [wyniki](hor-repro-results.json): oryginalne team_kpis i helpery ról; pierwsze rzeczywisteSQL na SQLite :memory:, pozostałe agregaty jako fixture’y. TCM + recruiter zostaje w wyniku, placement 1, 4 zapytania. Nie dowodzi danych rzeczywistego rosteru produkcji.

Testy wykonano host-native, Node 22.23.0, SQLAlchemy 2.0.51; istniejące zależności bez instalacji. Bez lokalnego Dockera, Postgresa, lifespan, LLM i produkcyjnych zapisów. Harnessy są kopiami dowodowymi; zawierają ścieżki `/tmp/nexus-performance-reaudit2-2026-09-14` i `/tmp/nexus-reaudit2-evidence-2026-09-14`. Przy przyszłym odtworzeniu użyć izolowanego checkoutu tego SHA i dostosować jawne ścieżki. Syntetyczny ciąg local-audit-token w teście nie jest poświadczeniem użytkownika.

## Odczyty operacyjne i UI

- [ui-observations.json](ui-observations.json): notatka z bezpośrednich obserwacji narzędzi Chrome. Źródła po kliknięciu kotwicy w świeżej karcie są widoczne; top 350 px, viewport 987 px. Zalogowany dashboard HoR załadował aktywność i listy. Konsola sprawdzana na poziomie error/warn nie zwróciła wpisów. Bez HAR, Web Vitals, ilościowego CLS i testowania zapisów.
- [staging-status.json](staging-status.json): wybrane metadane z autoryzowanego read-only [workflow staging-status](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34837698245). Job success, aplikacja exited:unhealthy, stary SHA/gałąź. Audyt nie uruchamiał ani nie zmieniał stagingu.
- [Ostatni Uptime](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34811125357):14.09 05:51 UTC, success.
- [Ostatni Sentry daily](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34756756967):13.09 12:19 UTC, success. Brak nowego dowodu odebrania telemetry po poprawkach; odczyt repozytoryjnej listy sekretów zwrócił 403. Nie pobierano wartości sekretów.
- [Ostatni backup drill](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34805878641):14.09 04:23 UTC, failure, bez nowego udanego runu. Przyczynę braku konfiguracji przed restore opisuje materiał pierwszego reaudytu.

Surowe logi GHA pozostawiono w katalogu tymczasowym, zamiast kopiować całą konfigurację operacyjną do repo. W raporcie użyto linków do konkretnych runów i przypiętych linii kodu. SHA256SUMS.json obejmuje utrwalone artefakty.

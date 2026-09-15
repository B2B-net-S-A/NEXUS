# Testowanie NEXUS: Hypothesis, Schemathesis i k6

## Co wykonuje się automatycznie

- **Hypothesis + time-machine:** `backend/tests/property/` jest zbierane przez
  zwykłe `pytest tests/` w czterech shardach CI. Do 100 przykładów na własność;
  arkusze XLSX: 30. Testy sprawdzają górny limit stawki, jednostki/waluty,
  precyzję MD ↔ godziny, umowne godziny miesiąca, daty warszawskie (w tym DST),
  kwoty importu i przemieszczanie kolumn arkusza.
- **Import do bazy:** istniejący test
  `test_reimporting_the_same_month_does_not_subtract_twice` generuje 6 par
  kwota/liczba powtórzeń. Każdy przykład zakłada własne rekordy i sprawdza
  wykorzystany oraz pozostały budżet po 2–4 importach tego samego miesiąca.
- **Schemathesis:** job `E2E stack (ci-chromium)` uruchamia `qa/api/` na
  istniejącym efemerycznym stacku CI. Pięć GET-ów: lista i szczegóły kandydatów,
  lista i szczegóły kontraktów, zamówienia klienta. Generator korzysta z OpenAPI
  faktycznie zbudowanej aplikacji. Dla list zakres wejścia to `q` (do 64 znaków),
  `page` (1–3), `page_size` (1–25); szczegóły używają istniejących identyfikatorów.
  Pozostałe opcjonalne filtry nie są objęte tym pierwszym zestawem.
  Pełne schematy odpowiedzi pozostają niezmienione. Do 30 przykładów na endpoint
  (generator może wyczerpać skończoną przestrzeń wcześniej), plus 8 przypadków
  odrzucenia błędnej paginacji. Poprawne żądanie musi zwrócić 200, błędna
  paginacja 422. Zniknięcie endpointu lub danych powoduje błąd, nie pominięcie.
- **k6:** trzy równoległe scenariusze HTTP: rekrutacja (lista → wyszukiwanie →
  profil → pipeline), operacje (kontrakty → szczegóły → zamówienia), raportowanie
  (dashboard pracy własnej i finansów). `smoke` = po 1 VU na scenariusz przez
  20 sekund. To nie jest pomiar renderowania przeglądarki ani wydajności AI.

Własności mają deterministyczną generację w CI i standardowe shrinking/replay
Hypothesis. Nie dodajemy tych zależności do produkcyjnego `requirements.txt`.

## Dane, bezpieczeństwo i granice pomiaru

`qa/prepare.py` tworzy przez API 12 kandydatów, 3 klientów, 3 rekrutacje i 3
kontrakty z aktywnymi zamówieniami. Wykorzystuje administratora i rekrutera z
`seed_e2e.py`; rekrutacje są przypisane do tego rekrutera. Schemathesis sprawdza
kontrakty jako administrator. Uprawnienia sprawdzają istniejące testy RBAC.

Dwa konta są współdzielone przez wirtualnych użytkowników. Ten mały zbiór
sprawdza wykonywalność ścieżek i regresje, **nie dowodzi gotowości produkcji na
100 użytkowników ani na obecną liczbę kandydatów**. Docelowy benchmark wymaga
reprezentatywnego zbioru, wielu kont, infrastruktury podobnej do produkcji,
metryk DB/aplikacji oraz osobnej próby ciągłości podczas wdrożenia. Testów tych
nie należy przedstawiać jako wykonanych przez ten pakiet.

Runner przyjmuje wyłącznie `http://localhost:8000` / `http://127.0.0.1:8000`
i `QA_CONFIRM=nexus-e2e`; nie śledzi przekierowań. `.qa/workload.json` zawiera
tymczasowe tokeny i ma prawa 0600. `.qa/` jest ignorowane przez Git i nigdy
nie trafia do artefaktów. Stack jest usuwany przez dotychczasowy krok `always()`.
Schemat pobieramy wewnątrz kontenera; publiczne OpenAPI pozostaje wyłączone.

## Progi i raporty

k6 wymaga 100% poprawnych sprawdzeń odpowiedzi, mniej niż 1% błędów HTTP,
HTTP p95 poniżej 3000 ms osobno dla każdego scenariusza i co najmniej jednego
ukończonego przepływu każdego rodzaju. To początkowe progi regresji CI, a nie
uzgodnione SLO produkcyjne. Nie zmniejszać rygoru w celu zazielenienia błędu.

Wyniki: artefakt `nexus-qa-toolkit` i podsumowanie joba, w tym
`schemathesis.xml`, `k6-summary.json`, `workload.json` (liczniki bez tokenów)
i `summary.md`. Błąd nowego testu oznacza czerwony job. Cały workflow E2E nie
jest obecnie wymagany przez ruleset repozytorium; ten PR nie zmienia polityki
dostępu/ochrony gałęzi. Przed merge tego pakietu wymagamy również jego sukcesu.

## Uruchomienie

Lokalnie bez Dockera, w środowisku Pythona backendu:

```sh
pip install -r backend/requirements-testing.txt
PYTHONPATH=backend CI=1 pytest backend/tests/property --confcutdir=backend/tests/property
python -m pytest qa/tests -q
```

Konfiguracja aplikacji musi być testowa (np. `DEBUG=true`); testy czyste nie
łączą się z bazą. Integracyjny test importu uruchamia hosted CI z PostgreSQL.

Pełny zestaw: GitHub Actions → **E2E (Playwright)** → Run workflow →
`k6_profile=smoke`. Do dłuższej próby na tym samym izolowanym stacku wybierz
`load`: pięć 60-sekundowych etapów rampy, około 10/25/50/100/0 VU, proporcje
60% rekrutacja / 25% operacje / 15% raportowanie (zaokrąglenia per scenariusz).
Domyślne biegi PR i nocne używają krótkiego profilu. Nie uruchamiamy lokalnego
Dockera ani obciążenia produkcji.

Wersje: Hypothesis 6.168.0, time-machine 3.5.1, Schemathesis 4.27.1, k6 2.2.0.
Archiwum k6 w CI jest weryfikowane SHA-256. Przy aktualizacji zmień wersję i
sumę razem, a następnie sprawdź raporty i wszystkie trzy ścieżki.

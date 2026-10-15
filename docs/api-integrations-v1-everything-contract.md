# API v1 — reszta procesów: kontrakt dla budowy (15.10.2026)

Decyzja Artura 15.10.2026 („rób wszystko”): API integracyjne v1 obejmuje wszystkie
procesy NEXUSA. Ten plik jest wspólnym kontraktem pięciu równoległych modułów; po
wdrożeniu jego treść trafia do `docs/api/integracje-v1.md`. Wcześniejsze części:
`docs/api-integrations-v1-recruitment-contract.md` (rekrutacja i kandydaci).

## Nowe scope'y (`app/models/service_account.py`, aliasy w `common.py`)

| Scope | Alias | Moduł |
|---|---|---|
| `recruitments:create` | `RecruitmentsCreate` | `recruitment_create.py` — odczyt requestu (AI) i założenie rekrutacji |
| `cv:generate` | `CvGenerate` | `cv.py` — generowanie CV dla klienta, status; pobranie pliku także z `candidates:cv` |
| `calendar:read` | `CalendarRead` | `calendar.py` — rozmowy u klienta, prepy, debriefy (odczyt) |
| `applications:read` / `applications:write` | `ApplicationsRead` / `ApplicationsWrite` | `applications.py` — zgłoszenia z linku rekrutacji |
| `insights:read` | `InsightsRead` | `insights.py` — raporty i wskaźniki |
| `academy:read` | `AcademyRead` | `academy.py` — programy i nabór |
| `events:read` / `webhooks:manage` | `EventsRead` / `WebhooksManage` | `events.py` — kanał zdarzeń i webhooki |

## Zasady wspólne (jak w poprzednich częściach)

- Moduły `integrations_v1` bez `from __future__ import annotations`; każda trasa:
  `@limiter.limit(read_rate_limit | write_rate_limit, key_func=principal_rate_key)`,
  `request: Request`, docstring, `response_model`; router `APIRouter(route_class=IntegrationRoute)`.
- Zapis: `idempotent_write` (`Idempotency-Key`), ciało bez `commit()`, efekty po commicie.
- Autor zapisu: `IntegrationActor` / `WriteAuthor` (`services/write_author.py`) — nigdy w
  bramkach ról (`has_role`, `has_permission`); `UserActivity` nie powstaje.
- Kwoty przez `amount_level(caller)`: koszt tylko `AmountLevel.all`, sprzedaż od `sales`.
- Dane kontaktowe kandydata tylko z `candidates:contact` (`sees_candidate_contact`),
  tekst/pliki CV z `candidates:cv` (`reads_candidate_cv`).
- Rekrutacje ukrytych i usuniętych klientów nie istnieją dla klucza
  (`jobs_register_base_clause`, `client_identity.job_client_listed_clause`).
- Wynik modelu AI jest podpowiedzią, nigdy warunkiem; model z rejestru `services/ai_models.py`
  w kontekście `ai_feature()`.
- Testy: Postgres jak `tests/test_integrations_v1_api.py` (fikcyjne osoby), testy bez bazy
  dla czystych funkcji. Snapshot OpenAPI i wzorce bramek odświeża koordynator.

## Zdarzenia (moduł `events.py`, migracja 0448)

- Tabela `integration_events`: `id` (bigserial, kursor), `type`, `occurred_at`,
  `refs` (JSONB z samymi identyfikatorami, np. `{"candidate_id": 1, "job_id": 2}`),
  `scope` (scope potrzebny, żeby zdarzenie zobaczyć). Bez danych osobowych i kwot.
- Zdarzenia powstają w listenerach ORM (jeden moduł, bez edycji ekranów), w tej samej
  transakcji co zmiana: kandydat dodany, karta przesunięta (nowy wiersz etapu), notatka,
  rekrutacja założona / zamknięta / wznowiona, zgłoszenie z linku, zmiana w zamówieniu
  (`order_change_events`), status kontraktu, import MD, faktura wystawiona / zmieniona.
- Kanał: `GET /events?after=<id>&types=` — zdarzenia, które konto może zobaczyć (scope).
- Webhooki konta: `GET/POST/DELETE /webhooks`, `POST /webhooks/{id}/test`. Adres tylko
  `https://`, bez adresów prywatnych/lokalnych (ochrona SSRF przy zapisie i przy wysyłce),
  podpis HMAC-SHA256 treści sekretem webhooka (sekret pokazany raz), ponowienia z odstępem,
  wyłączenie po serii porażek. Wysyłka w tle (pętla w `main.py`), treść = to samo co w kanale.
- Ekran „Klucze API” pokazuje webhooki konta (odczyt dla admina).

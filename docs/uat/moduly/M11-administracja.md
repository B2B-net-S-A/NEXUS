# M11 — Administracja (Ustawienia)

| Pole | Wartość |
|---|---|
| Tryb | **R** — ŻADNYCH zapisów w Ustawieniach (wpływ natychmiastowy na wszystkich) |
| Persony | admin; do negatywnych: finance, delivery_lead, recruiter (podgląd) |
| Zależności | Fala 0 |
| Czas | ~2,5 h |
| Głębokość | przegląd + pełna dla uprawnień i AI |
| Akcje AI | nie (S14 „Test alertu” — **nie klikaj**) |

## Zakres

`/settings` — zakładki: **Integracje · Szablony email · Coaching KPI · Procesy · Administracja · Zaawansowane · Pomoc**
(`?tab=`; sub-routing `/settings/profile` = 404, `?tab=profile` działa — znane).
Podstrony: `/settings/ai`, `/settings/api-integration`, `/settings/chats`, `/settings/client-portfolio-preview`,
`/settings/clients-overview`, `/settings/contract-templates`, `/settings/cv-rules` (M05), `/settings/diagnostics`,
`/settings/dictionaries`, `/settings/entity-fields`, `/settings/hiring-managers`, `/settings/linkedin-metrics`,
`/settings/pipeline-templates`, `/settings/rate-benchmarks`, `/settings/scoring`, `/settings/team-structure`, `/settings/templates`.
Administracja → Użytkownicy (podgląd jako…), Uprawnienia (sekcje per rola/użytkownik, akcje), Konta serwisowe, System (statystyki).

## NIE KLIKAJ

Wszystko, co zapisuje: role, aktywność użytkownika, uprawnienia sekcji/akcji, master toggle AI,
limity, „Test alertu”, szablony, słowniki, szablony pipeline'u, wagi scoringu, „Wydaj klucz”/„Odwołaj klucz”,
„Zresetuj hasło”, „Wyślij link resetu”, backfille, sync Traffita, naprawy indeksu, „Aplikuj manifest”.

## Scenariusze

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | admin | `/settings` → każda z 7 zakładek | ładują się; `?tab=` w URL; F5 odtwarza | P1 |
| S02 | admin | Administracja → Użytkownicy | lista z rolą, aktywnością, `last_activity`; wyszukiwanie; ikona oka „Podgląd jako ten użytkownik” przy aktywnych ≠ ja; brak ikony przy nieaktywnych i przy sobie | P1 |
| S03 | admin | Użytkownicy → filtr roli, nieaktywni | działa; licznik | P2 |
| S04 | admin | Administracja → Uprawnienia (sekcje) | macierz rola × 6 sekcji (`none/read/write`); `locked` sekcje oznaczone; nadpisania per użytkownik z `inherit`; **tylko czytaj**; zapisz zrzut jako źródło prawdy dla karty A | P1 |
| S05 | admin | Uprawnienia → akcje (`action_permissions`) | lista akcji produktu z dostępem per rola | P2 |
| S06 | admin | Konta serwisowe | lista (scope'y `traffit:sync`, `traffit:read`, `ops:snapshot`, `contractors:read`); klucze z `expires_at`, `last_used_at`; **nie wydawaj** | P1 |
| S07 | admin | System (statystyki) | liczniki (użytkownicy, kandydaci, …) zgodne z listami (porównaj 2); wersja = SHA testowany | P2 |
| S08 | admin | `/settings/ai` | master toggle, lista funkcji z `enabled`, `monthly_limit`, zużycie; ostrzeżenia zużycia; **nie przełączaj** | P1 |
| S09 | admin | `/settings/ai` → funkcja z zużyciem ≥ 80 % (jeśli jest) | wyróżnienie; zapisz nazwę do raportu (budżet UAT) | P2 |
| S10 | admin | `/settings/diagnostics` | health, deep health, alembic, schema drift (`/api/admin/schema-drift` → 200 z `error` lub czysto); brak 500 przy timeoutcie | P1 |
| S11 | admin | `/settings/pipeline-templates` | szablony (Default B2B…) z etapami; kolejność; **nie edytuj** | P2 |
| S12 | admin | `/settings/scoring` | wagi; suma/opis; **nie zapisuj** | P2 |
| S13 | admin | `/settings/dictionaries`, `/settings/entity-fields` | listy; walidacja formularza PL (otwórz i Anuluj) | P3 |
| S14 | admin | `/settings/templates` (szablony email), `/settings/contract-templates` | listy; podgląd szablonu renderuje zmienne; **nie wysyłaj testowego** | P2 |
| S15 | admin | `/settings/team-structure`, `/settings/hiring-managers`, `/settings/linkedin-metrics` | ładują się; dane; brak 500 | P2 |
| S16 | admin | `/settings/client-portfolio-preview` | podgląd manifestu portfela; `get_client_portfolio_import_health` zielony (uwzględnia `purged_at`) | P2 |
| S17 | admin | `/settings/api-integration` | klucze OAuth klientów / webhooki; **nic nie generuj** | P3 |
| S18 | admin | Integracje: M365 (połączenie skrzynki), CloudTalk (karta zdjęta), Traffit status | M365 połączone; Traffit: watermark, fazy, `degraded` z powodem | P1 |
| S19 | finance | `/settings` → Administracja | zakładka niewidoczna / odmowa; `/settings/chats` DOSTĘPNE | P1 |
| S20 | delivery_lead | `/settings/cv-rules` (M05 S26), `/settings/ai` | cv-rules tak; ai → odmowa | P1 |
| S21 | recruiter | `/settings/templates` | dostępne (NON_FINANCE_ROLES); `/settings/scoring` → odmowa | P2 |
| S22 | admin | Użytkownicy → osoba z rolą `user` (legacy) | oznaczenie „wycofywana”; brak możliwości nadania `user` nowemu (formularz roli bez tej opcji) | P2 |
| S23 | admin | Użytkownicy → „Dodaj użytkownika” → formularz → Anuluj | domyślna rola `recruiter`; walidacja domeny e-mail (`SSO_ALLOWED_DOMAINS`) w komunikacie PL | P2 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const sp = await fetch('https://api.nexus.dynaminds.pl/api/admin/section-permissions',{headers:h}).then(r=>r.json());
console.log('revision', sp.revision); console.table(sp.roles.map(r=>({role:r.role, ...r.permissions})));
// ↑ ZAPISZ do wyniki/M11/section-permissions.json — to źródło prawdy dla karty A
const sa = await fetch('https://api.nexus.dynaminds.pl/api/settings/service-accounts',{headers:h}); console.log('service accounts', sa.status);
const sd = await fetch('https://api.nexus.dynaminds.pl/api/admin/schema-drift',{headers:h}).then(r=>r.json()); console.log(sd.error ?? 'drift ok', sd.alembic);
```

## Znane pułapki

- Konfiguracja uprawnień na prodzie może różnić się od domyślnej z kodu — **konfiguracja wygrywa**.
- `/settings/profile` 404 to znany stan (sub-routing); `?tab=profile` działa.
- `schema-drift` robi rollback w każdej gałęzi błędu — 200 z polem `error` to poprawny kontrakt, nie awaria.

## Do raportu

`section-permissions.json`, zrzut listy funkcji AI ze zużyciem, tabela „rola → które podstrony `/settings/*` dostępne”.

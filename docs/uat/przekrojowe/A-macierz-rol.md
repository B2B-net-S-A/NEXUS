# A — Kontrola przekrojowa: macierz ról (każdy ekran × każda rola)

| Pole | Wartość |
|---|---|
| Tryb | **R** (podgląd) |
| Persony | WSZYSTKIE 9 ról (8 + `user`, jeśli istnieje aktywne konto) |
| Zależności | M11 S04 (`section-permissions.json` — źródło prawdy konfiguracji), Fala 0 persony |
| Czas | ~4 h (≈ 25 min na rolę) |
| Głębokość | pełna |
| Akcje AI | nie |

## Cel

Jedna osoba (agent) przechodzi TE SAME 30 tras oczami każdej roli i wypełnia jedną tabelę.
Karty modułów testują funkcje; ta karta testuje granice. Wynik jest tabelą, nie prozą.

## Przed startem

1. Wczytaj `wyniki/M11/section-permissions.json` — jeśli różni się od [03-macierz-rol.md §2](../03-macierz-rol.md),
   **konfiguracja wygrywa**; zapisz różnice w raporcie i testuj według konfiguracji.
2. Dla każdej persony: `GET /api/auth/me` w podglądzie → zapisz `role`, `roles`, `data_scope`, `effective_permissions`.
3. Wyłącz podgląd między rolami (`localStorage.removeItem('nexus_impersonate_id')` + F5), żeby nie mieszać sesji.

## Lista tras (30) — dla KAŻDEJ roli

| # | Trasa | Oczekiwanie wg roli (domyślne; konfiguracja wygrywa) |
|---|---|---|
| 1 | `/dashboard` | wszyscy: dashboard SWOJEJ roli |
| 2 | `/candidates` | wszyscy poza USR; FIN pełny odczyt |
| 3 | `/candidates/{{D5}}` | jw.; stawka kandydata widoczna dla ról operacyjnych |
| 4 | `/candidates/contact-queue` | TCM, TAC, REC, SRC (menu); ADM — trasa działa bez pozycji w menu |
| 5 | `/candidates/search` | jak 2 |
| 6 | `/talent-radar` | KAŻDA rola |
| 7 | `/cv-generator` | role sekcji sourcing bez USR |
| 8 | `/contracts/b2b-generator` | KAŻDA rola; DL tylko z przypisanym klientem (lista może być pusta z komunikatem) |
| 9 | `/talents`, `/sourcing/marketplace`, `/applications` | wszyscy poza USR |
| 10 | `/jobs` | role sekcji pipeline; FIN odczyt |
| 11 | `/jobs/{{D3}}` | jw.; TAC spoza zespołu: odczyt, ruch zablokowany z powodem |
| 12 | `/calendar` | role sekcji pipeline |
| 13 | `/clients` | role sekcji delivery; REC/SRC → odmowa |
| 14 | `/clients/{{D1}}` (przypisany DL 30) | DL 30: pełny z kwotami; TCM: bez kwot; FIN/ADM: z kwotami; HoR/TAC/REC/SRC: odmowa |
| 15 | `/clients/{{D2}}` (bez przypisań DL) | DL: profil OK, kwoty „—”; reszta jak 14 |
| 16 | `/clients/{{D1}}?tab=zamowienia` | jak 14; stawki linii MD tylko ADM + DL przypisany do klienta |
| 17 | `/my-clients` | DL/FIN/TCM: wszyscy klienci; HoR/TAC/REC → odmowa |
| 18 | `/my-relationships` | role sekcji delivery |
| 19 | `/order-mail` | role sekcji delivery; TCM bez treści błędów i bez „Pobierz”; REC → odmowa |
| 20 | `/contracts` | role sekcji delivery; kwoty tylko `view_finance` (ADM, FIN) |
| 21 | `/contractors` | jw. |
| 22 | `/dashboard/delivery-lead` | ADM, DL, HoR |
| 23 | `/insights` (3 zakładki) | KAŻDA rola |
| 24 | `/cortex` | role sekcji insights bez USR |
| 25 | `/finance` | ADM, FIN; reszta → odmowa |
| 26 | `/settings` | wszyscy; zakładka Administracja tylko ADM |
| 27 | `/settings/ai`, `/settings/scoring`, `/settings/pipeline-templates` | ADM (wg middleware); reszta → odmowa |
| 28 | `/settings/cv-rules` | ADM, DL; TAC → odmowa |
| 29 | `/settings/chats` | ADM, FIN |
| 30 | `/dynareporter/board-dashboard` | ADM, DL, HoR (jeśli DR w zakresie) |

## Procedura per rola

1. Włącz podgląd persony. Zrzut sidebaru → `zrzuty/A-<rola>-sidebar.png`.
2. Dla tras 1–30: wejdź, zaczekaj na załadowanie, zapisz w tabeli JEDNĄ z wartości:
   - `OK` — ładuje się, treść zgodna z oczekiwaniem,
   - `OK-noqty` — ładuje się, kwoty „—” (gdy tak ma być),
   - `DENY` — `/403` lub czytelna odmowa PL (gdy tak ma być),
   - `!LEAK` — widać coś, czego rola nie powinna widzieć (dane/kwoty/akcje) → **P0**,
   - `!DENY-on-link` — link był w menu, a strona odmawia → **P1**,
   - `!EMPTY` — pusta lista/pusty ekran zamiast odmowy lub błędu → **P1**,
   - `!ERR` — 5xx / biały ekran → **P1**.
3. Mutacja w podglądzie (raz per rola): `POST /api/notes` `{ "content": "[QA-E2E] A-test", "candidate_id": {{D5}} }`
   z `X-Impersonate-User-Id` → oczekiwane 403 read-only. Inny wynik → **P0**.
4. Trzy trasy „nie moje” wpisane ręcznie (dobierz do roli: REC → `/finance`, `/settings/ai`, `/clients/{{D1}}`;
   FIN → `/settings/ai`, `/cortex` kuratela, `/dynareporter/admin-dashboard`; DL → `/finance`, `/settings/ai`; HoR/TAC → `/clients`, `/contracts`).

## Wynik — `wyniki/A/macierz.md`

```markdown
| Trasa | ADM | HoR | DL | TCM | FIN | TAC | REC | SRC | USR |
|---|---|---|---|---|---|---|---|---|---|
| /dashboard | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| /clients/{{D1}} | OK | OK-noqty | OK | OK-noqty | OK | OK-noqty | DENY | DENY | DENY |
| … |
```
+ lista zgłoszeń (każde `!` = zgłoszenie z zrzutem i statusem HTTP) + `auth-me/<rola>.json`.

## Reguły oceny

- **Redakcja całościowa albo żadna**: na jednej stronie kafel z kwotą + kolumna „—” = P1.
- Widoczny przycisk akcji ≠ uprawnienie. Zapisz, ale nie klikaj. Przycisk widoczny roli bez prawa
  (np. „Czyszczenie listy” dla DL) = P2 (UI), chyba że API przepuszcza — wtedy P0 (sprawdź API GET/odpowiednik read-only; mutacji NIE).
- Odmowa musi być odmową: `/403`, komunikat PL. Pusta lista jako odmowa = P1 (czyta się jak utrata danych).

# RBAC — Role-Based Access Control

## Stan aktualny — macierz sekcji (2026-09-02)

Źródłem prawdy backendu jest `backend/app/api/section_access.py`, a jego
frontendowym lustrem `frontend/src/lib/section-access.ts`. Legenda: **RW** —
odczyt i zapis, **R** — odczyt, **—** — brak dostępu. To maksymalny dostęp do
sekcji; guard konkretnej akcji lub rekordu może go dodatkowo zawęzić.

| Rola | Sourcing | Pipeline | Delivery | Insights | Finanse | Administracja techniczna |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Administrator | RW | RW | RW | RW | RW | RW |
| Finanse | RW | RW | RW* | R | RW | — |
| Head of Recruitment | RW | RW | — | RW | — | — |
| Delivery Lead | RW | RW | RW** | R | — | — |
| Talent Community Manager | RW | RW | R*** | R | — | — |
| TAC | RW | RW | — | R | — | — |
| Rekruter | RW | RW | — | R | — | — |
| Sourcer | RW | RW | — | R | — | — |
| Viewer `user` (legacy) | R | R | — | R | — | — |

\* Finanse zachowują istniejące procesy rozliczeniowe w Delivery, ale konkretne
operacje nadal mają osobne guardy.

\** Delivery Lead działa wyłącznie na klientach jawnie przypisanych w relacji
DL→klient. Pusty portfel oznacza brak rekordów, a nie dostęp globalny.

\*** Talent Community Manager ma globalny, bezpieczny odczyt operacyjny Delivery.

### Kluczowe granice

- **TCM:** pełny Sourcing i Pipeline, odczyt Insights oraz globalny odczyt
  ustrukturyzowanych danych Delivery. W Delivery: bez zapisów, stawek, marż,
  przychodu, surowych umów/aneksów/PO i rate-bearing eksportów. Nie ma dostępu
  do modułu Finanse.
- **Delivery Lead:** nie wchodzi do globalnego modułu Finanse. W swoim portfelu
  Delivery widzi stawki i marże potrzebne do obsługi klienta. Wyjątek jest
  liczony per klient i nie nadaje globalnej capability `view_finance`.
- **Sourcer, Rekruter, TAC i HoR:** mają Sourcing, Pipeline i Insights, ale UI
  nie pokazuje im Delivery/Finansów, a bezpośrednie wejście do API kończy się
  `403`.
- **Administracja techniczna:** użytkownicy/role, globalne AI, klucze
  integracji, diagnostyka, słowniki systemowe i konfiguracja pól pozostają
  Administrator-only. Ustawienia biznesowe mają własne jawne publiczności.
- **Wielorola:** dostęp sekcyjny jest sumą ról, ale obecność roli Delivery Lead
  nadal wymusza zakres przypisanych klientów (poza Administratorem). Rola
  Finanse pozostaje ekskluzywna.
- **Insights:** zachowuje osobną, istniejącą politykę transparentności D7 dla
  całej firmy, również dla części kwot i danych imiennych. Brak dostępu do
  modułu Finanse nie oznacza redakcji uzgodnionych metryk wewnątrz Insights.

Autoryzacja działa warstwowo: bramka sekcji → guard akcji → scope rekordu →
redakcja odpowiedzi. Middleware i sidebar są warstwą UX; backend pozostaje
ostatecznym arbitrem. Nowa rola lub endpoint muszą zostać jawnie dopisane do
obu macierzy, otrzymać guard akcji i test pełnej macierzy ról.

---

## Historyczna dokumentacja Phase 8

Poniższa część opisuje pierwotny model Phase 8 i służy jako kontekst migracji.
Nie jest aktualną macierzą uprawnień; w razie rozbieżności obowiązuje sekcja
„Stan aktualny” powyżej oraz kod źródłowy wskazany w jej wstępie.

**Status:** Phase 8 (2026-04)
**Enum źródłowy:** `backend/app/models/user.py` → `UserRole`
**Guardy backend:** `backend/app/api/deps.py`
**Middleware frontend:** `frontend/src/middleware.ts`
**Helpery frontend:** `frontend/src/store/auth.ts` (`hasRole`, `hasMinRole`, `ROLE_RANK`)

---

## 1. Model ról

Jedna hierarchia, sześć wartości. Każdy user ma dokładnie jedną rolę
(nie ma już dwóch pól jak w poprzednim `UserRole` + `RecruiterRole`).

| Role | Ranga | Kto | Kluczowe uprawnienia |
|---|:---:|---|---|
| `admin` | 5 | Właściciel, CTO | Zarządzanie userami, systemem, wszystkie dane |
| `delivery_lead` | 4 | DL procesu | Rate cards, konflikty, pipeline templates, pełne raporty, zespół |
| `tac` | 3 | Talent Acquisition Consultant | CRUD ofert/kontraktów, reject/offer, prep kit, pełne raporty |
| `recruiter` | 2 | Rekruter (100% LinkedIn) | Dodawanie kandydatów, ruchy w pipeline, własne raporty |
| `sourcer` | 2 | Sourcer (100% ATS/ogłoszenia) | Dodawanie kandydatów z bazy, ruchy w pipeline, własne raporty |
| `user` | 1 | QC, klient, viewer | Read-only across UI |

`recruiter` i `sourcer` są na tej samej randze — różnią się **kompetencją**
(LinkedIn vs ATS), nie poziomem uprawnień. System premiowy B2B.net rozróżnia
ich per-kandydat w systemie aktywności (kto dodał, kto przesunął).

---

## 2. Trzy warstwy autoryzacji (defense in depth)

### 2.1 API level — FastAPI guardy

Każde wywołanie API przechodzi przez `deps.py::get_current_user` (walidacja JWT +
`is_active`), a potem przez guard roli dla danego endpointu. Niedozwolona rola
= `403 Forbidden` zwrócone *przed* wykonaniem handlera. **To jest ostateczny
arbiter.**

Pipeline:

```
HTTP request → HTTPBearer → decode_token (signature + exp)
             → User lookup (is_active check)
             → require_roles(...)  → 403 if role not allowed
             → endpoint handler
```

### 2.2 Route level — Next.js middleware

`frontend/src/middleware.ts` dekoduje payload JWT z cookie `nexus_access`
(bez weryfikacji podpisu — middleware Edge Runtime nie ma dostępu do
`SECRET_KEY`). Sprawdza tylko:

- Cookie obecny? Jeśli nie → `/login?next=<pathname>`
- Token wygasł / źle sformatowany? → clear cookie + `/login`
- Rola spełnia wymagania route'u? Jeśli nie → `/403`

**To jest UX guard — nie bezpieczeństwo.** Ktoś z zepsutym JWT nadal nie
dostanie się do API (walidacja backendowa w 2.1), ale zostanie przed
rozerwanym UI.

### 2.3 UI level — `<RequireRole>` component

`frontend/src/components/RequireRole.tsx` kontroluje widoczność pojedynczych
elementów (przycisków, sekcji, linków w sidebarze). **Cosmetic gating** —
user i tak dostanie 403 jeśli ręcznie wysłałby request.

---

## 3. Guardy backendu — macierz

Zdefiniowane w `backend/app/api/deps.py`:

| Guard | Dozwolone role |
|---|---|
| `CurrentUser` | dowolna zalogowana rola |
| `AdminUser` | `admin` |
| `DeliveryLeadPlus` | `admin`, `delivery_lead` |
| `TacPlus` | `admin`, `delivery_lead`, `tac` |
| `RecruiterPlus` | `admin`, `delivery_lead`, `tac`, `recruiter`, `sourcer` (wszyscy poza `user`) |
| `ManagerOrAdmin` | alias do `DeliveryLeadPlus` (backward compat) |

---

## 4. Macierz per-endpoint

Lista endpointów i ich aktualne guardy (po phase 8). Endpointy nie wymienione
domyślnie używają `CurrentUser`.

### 4.1 `/api/admin/*` — AdminUser

| Endpoint | Guard |
|---|---|
| `GET /api/admin/users` | AdminUser |
| `POST /api/admin/users` | AdminUser |
| `PUT /api/admin/users/{id}` | AdminUser |
| `DELETE /api/admin/users/{id}` | AdminUser |
| `POST /api/admin/users/{id}/reset-password` | AdminUser |
| `GET /api/admin/system` | AdminUser |

### 4.2 `/api/jobs/*` — Tac+

| Endpoint | Guard |
|---|---|
| `GET /api/jobs` | CurrentUser |
| `GET /api/jobs/{id}` | CurrentUser |
| `GET /api/jobs/{id}/match-candidates` | CurrentUser |
| `POST /api/jobs` | TacPlus |
| `PATCH /api/jobs/{id}` | TacPlus |
| `DELETE /api/jobs/{id}` | TacPlus |
| `POST /api/jobs/{id}/publish` | TacPlus |
| `POST /api/jobs/{id}/refresh-criteria` | DeliveryLeadPlus (via `require_roles`) |
| `POST /api/jobs/{id}/generate-criteria-preview` | DeliveryLeadPlus |
| `POST /api/jobs/{id}/recompute-scores` | DeliveryLeadPlus |

### 4.3 `/api/contracts/*` — Tac+

| Endpoint | Guard |
|---|---|
| `GET /api/contracts` | CurrentUser |
| `GET /api/contracts/{id}` | CurrentUser |
| `GET /api/contracts/expiring` | CurrentUser |
| `POST /api/contracts` | TacPlus |
| `PATCH /api/contracts/{id}` | TacPlus |
| `DELETE /api/contracts/{id}` | TacPlus |

### 4.4 `/api/candidates/*` — Recruiter+

| Endpoint | Guard |
|---|---|
| `GET /api/candidates` | CurrentUser |
| `GET /api/candidates/export` | CurrentUser |
| `GET /api/candidates/{id}` | CurrentUser |
| `GET /api/candidates/{id}/timeline` | CurrentUser |
| `GET /api/candidates/{id}/history` | CurrentUser |
| `GET /api/candidates/{id}/cv-download` | CurrentUser |
| `POST /api/candidates` | RecruiterPlus |
| `POST /api/candidates/bulk-import` | RecruiterPlus |
| `POST /api/candidates/{id}/cv` | RecruiterPlus |
| `POST /api/candidates/check-duplicates` | CurrentUser |
| `PATCH /api/candidates/{id}` | RecruiterPlus |
| `DELETE /api/candidates/{id}` | **DeliveryLeadPlus** |

### 4.5 `/api/pipeline/*` — Recruiter+

| Endpoint | Guard |
|---|---|
| `GET /api/pipeline/stages` | CurrentUser |
| `GET /api/pipeline/kanban/{job_id}` | CurrentUser |
| `GET /api/pipeline/overview` | CurrentUser |
| `POST /api/pipeline/move` | RecruiterPlus |
| `POST /api/pipeline/bulk-move` | RecruiterPlus |

### 4.6 `/api/reports/*` — Tac+

| Endpoint | Guard |
|---|---|
| `GET /api/reports/recruitment` | TacPlus |
| `GET /api/reports/sales` | TacPlus |
| `GET /api/reports/delivery-leads` | TacPlus |
| `GET /api/reports/tenders` | TacPlus |
| `GET /api/reports/board` | TacPlus |

### 4.7 `/api/phase5/*` + `/api/pipeline-templates/*` — DeliveryLeadPlus

Rate cards, konflikty, templates — zarządzanie procesem. Wymaga DL+ (via
alias `ManagerOrAdmin` = `DeliveryLeadPlus`).

### 4.8 `/api/clients/*` — Tac+

| Endpoint | Guard |
|---|---|
| `GET /api/clients` | CurrentUser |
| `GET /api/clients/{id}` | CurrentUser |
| `POST /api/clients` | TacPlus |
| `PATCH /api/clients/{id}` | TacPlus |
| `DELETE /api/clients/{id}` | **DeliveryLeadPlus** |

Dodane w PR #17 — poprzednio wszystko pod `CurrentUser` (brak guarda na
business-critical CRUD, niespójne z jobs/contracts).

### 4.9 `/api/auth/*` — mix

| Endpoint | Guard | Uwagi |
|---|---|---|
| `POST /api/auth/login` | brak (public) | Rate limit 5/min per IP |
| `POST /api/auth/register` | brak (public) | Rate limit 3/min. Rola default=recruiter |
| `POST /api/auth/refresh` | brak (token-based) | Rate limit 10/min |
| `GET /api/auth/me` | CurrentUser | |
| `POST /api/auth/change-password` | CurrentUser | Rate limit 3/min. Weryfikuje `current_password`, `new_password` ≥ 8 znaków, rzuca 400 gdy identyczne. Dodany w PR #17 |

---

## 5. Frontend — route gating (middleware)

`frontend/src/middleware.ts`:

| Prefix | Dozwolone role |
|---|---|
| `/admin/*` | `admin` |
| `/manager/*` | `admin`, `delivery_lead` |
| `/reports/*` | `admin`, `delivery_lead`, `tac` |
| `/candidates`, `/jobs`, `/contracts`, `/contacts`, `/clients`, `/talents`, `/calendar`, `/profile`, `/analytics`, `/settings` | każdy zalogowany |
| `/login`, `/403`, `/_next/*` | publiczny |

Niedozwolona rola → redirect `/403`. Brak tokena → `/login?next=<path>`.

---

## 6. Frontend — UI gating

```tsx
import { RequireRole } from "@/components/RequireRole"

// Exact match
<RequireRole roles={["admin", "delivery_lead"]}>
  <AdminPanel />
</RequireRole>

// Hierarchiczne ≥
<RequireRole minRole="tac">
  <RateCardsButton />
</RequireRole>
```

W `Sidebar.tsx` elementy nawigacji mają opcjonalne pole `roles` — jeśli
obecne, link widoczny tylko dla matching roli. Sekcje bez ani jednego
widocznego linku są ukrywane w całości.

---

## 7. Jak dodać nowy endpoint

1. **Zdecyduj warstwę uprawnień** wg macierzy: read (CurrentUser) /
   operational (RecruiterPlus) / sales (TacPlus) / process management
   (DeliveryLeadPlus) / admin (AdminUser).
2. **Dodaj typ** `current_user: TacPlus` (albo inny Annotated) zamiast
   `CurrentUser`.
3. **Dodaj wiersz** do macierzy w tym dokumencie.
4. **Dodaj test** w `backend/tests/test_rbac.py` — parametryzowany dla
   każdej roli, expected 200/403.

---

## 8. Jak zmigrować danego usera na inną rolę

```python
# Via admin endpoint
PUT /api/admin/users/{user_id}
{"role": "delivery_lead"}

# Via psql (awaryjnie)
UPDATE users SET role = 'tac' WHERE email = 'user@example.com';
```

Zmiana roli NIE unieważnia aktywnych tokenów — użytkownik zachowa stare
uprawnienia do końca życia tokena (max 8h). Aby wymusić logout:
`UPDATE users SET is_active = false; ... UPDATE users SET is_active = true;`
(`is_active=false` blokuje natychmiast w `get_current_user`).

---

## 9. Historyczny kontekst

Poprzedni model miał dwa enumy:

- `UserRole`: `admin | recruiter | manager | client`
- `RecruiterRole`: `recruiter | sourcer | tac | delivery_lead | quality_control | admin`

Pierwszy dla auth/JWT, drugi dla procesu rekrutacyjnego — ale żaden
endpoint nie używał `recruiter_role` do autoryzacji, więc była to dead
complexity.

Migracja `backend/alembic/versions/0011_consolidate_user_roles.py`
mapuje stare pary `(role, recruiter_role)` na jedno nowe pole `role`
z 6 wartościami. Downgrade jest best-effort (pewna informacja tracona
— np. QC i client dają oba `user` po migracji, downgrade nie odróżni
ich).

---

## 10. Emergency reset hasła (admin out-of-band)

Gdy nikt nie zna hasła admin'a (zgubiony password manager, reset
personelu, fresh deploy): jest CLI w backendzie który omija API.

```bash
# Przez Coolify shell lub SSH do backend container
docker exec -w /app nexusats-backend-1 \
  python scripts/reset_password.py <email> <new_password>
```

Script (`backend/scripts/reset_password.py`):
- Walidacja: user istnieje, hasło ≥ 8 znaków, DATABASE_URL w env
- Haszowanie przez bcrypt (passlib, zgodnie z `/api/auth/login`)
- Commit bezpośredni do tabeli `users` (omija guardy)

Bezpieczeństwo: kto ma shell do backend container, ma wszystko — stąd
script wymaga tylko tego dostępu. Nie loguje hasła. Exit codes: 0 OK,
1 missing args, 2 hasło za krótkie, 3 user nie znaleziony, 4 brak
DATABASE_URL.

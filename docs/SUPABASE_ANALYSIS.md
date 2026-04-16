# Analiza: Supabase vs self-hosted (Hetzner) dla Nexus ATS

**Data:** 2026-04-16
**Autor:** Claude Code (analiza techniczno-biznesowa)
**Status:** draft do decyzji

---

## 1. Stan obecny — twarde dane

### Kod

| Warstwa | LOC | Komponenty |
|---|---:|---|
| Backend (FastAPI) | **16 352** | 25 modeli SQLAlchemy, 36 routerów API, 10 migracji Alembic, 8 serwisów, 2 scheduled tasks |
| Frontend (Next.js 15) | **23 805** | React 19, Zustand, TanStack Query, Tailwind, Playwright E2E, Vitest |
| **Razem** | **~40k LOC** | + docker-compose (Coolify-ready) |

### Infrastruktura

- **Hetzner + Coolify** (self-hosted, Niemcy) — zgodnie z pamięcią `reference_infrastructure.md`
- **PostgreSQL 16** (Docker, volume `postgres_data`)
- **Qdrant** (wektory CV, 1024-dim embeddingi Voyage AI)
- **Ollama** (lokalny LLM dla niektórych AI features)
- **Backendowe integracje:** Voyage AI (HTTP), Fireflies (GraphQL), Sentry (SaaS)
- **WebSocket notifications** — własna implementacja (`app/api/ws.py`, connection manager, per-user broadcast, ping/pong)
- **Scheduled tasks** — `match_history_ttl`, `slack_sla_alerts`
- **Faza 7d (dopiero co zamknięta):** backup drill, auto-deploy webhook Coolify, frontend Vitest + Playwright, backend integration tests, observability

### Auth dziś

- JWT HS256 (access 8h, refresh 30d stateless)
- bcrypt (passlib)
- slowapi rate limit (5/min login, 3/min register, 10/min refresh)
- Brak: self-service reset hasła, OAuth, MFA, email verification
- Tokeny w `localStorage` (XSS surface)
- Endpoint `/api/admin/users` — admin resetuje hasła ręcznie

### Skala docelowa (z pamięci + REQUIREMENTS)

- **Użytkownicy wewnętrzni:** 5–15 osób (TAC, Sourcer, Rekruter, DL, Admin, User)
- **Brak portalu kandydata** (REQUIREMENTS_V2.md — rekruterzy wprowadzają kandydatów ręcznie)
- **Brak klientów self-service** (rola `user`/`client` to read-only dla DL/wewnętrznego QC)
- **Kandydaci w bazie:** perspektywicznie kilka–kilkanaście tysięcy
- **CV files:** obecnie w volume `/tmp/nexus/uploads` — docelowo do S3-like

---

## 2. Co daje Supabase — konkretnie, po kolei

| Produkt | Wartość dla Nexus |
|---|---|
| **Supabase Auth (GoTrue)** | Self-service password reset (+ SMTP), OAuth (Google, LinkedIn, GitHub…), MFA TOTP, email verification, account lockout — wszystko gotowe |
| **Postgres + RLS** | Ten sam Postgres, który masz, + Row-Level Security jako natywny mechanizm RBAC. Policy `USING (auth.jwt() ->> 'role' IN ('admin','delivery_lead'))` zastępuje guardy FastAPI |
| **Realtime** | WebSocket streamujący zmiany w tabelach. Mógłby zastąpić `ws.py` dla notyfikacji opartych o DB change |
| **Storage** | S3-like, integruje się z RLS. Dla CV files — win (obecny volume nie ma offsite backupu) |
| **Edge Functions** | Deno serverless; dla prostych integracji (webhooki Fireflies, cron) |
| **pgvector** | Rozszerzenie Postgresa; teoretycznie zastępuje Qdrant dla embeddingów |
| **Dashboard + SQL editor** | Przyjemny DX — ad-hoc queries, log viewer, schema designer |
| **PITR backupy** | Point-in-time recovery (7 dni na Pro, 14 dni na Team) — zastępuje twój backup drill |
| **Managed upgrades** | Postgres security patches automatycznie |

---

## 3. Argumenty ZA migracją (honestly)

### 3.1 Auth — realna wartość

- **Reset hasła self-service.** Dziś admin musi resetować hasła ręcznie przez `/api/admin/users/{id}/reset-password`. Dla zespołu 15 osób to może być 2–5 resetów/miesiąc — drobny ból, ale stały.
- **OAuth LinkedIn.** Dla rekruterów, którzy **żyją w LinkedIn** (REQUIREMENTS_V2.md: „Recruiter — 100% LinkedIn"), logowanie LinkedInem to realne UX. Plus może odblokować przyszłą integrację OAuth (np. pobieranie profili).
- **MFA dla admina.** Twój admin (Ty) ma dostęp do pełnej bazy kandydatów — MFA to dobre zabezpieczenie, samemu to napisać zajmie dzień.
- **Email verification + account lockout** — compliance posture, gdyby kiedyś trafił się klient wymagający SOC2-lite.

### 3.2 RLS > ręczne guardy — techniczna elegancja

Policy pisana raz w SQL obowiązuje **każdy query** na tabelę — w FastAPI, Edge Function, Dashboard, raw SQL. Eliminuje klasę bugów typu „zapomniałem `Depends(TacPlus)` na nowym endpoincie".

Dla RBAC z 6 rolami × 25 modeli = potencjalnie 150 punktów kontroli. RLS to 25 policy files.

### 3.3 Storage dla CV

Obecny `/tmp/nexus/uploads` to volume Dockera. W backup drill pewnie masz to pokryte, ale:
- Brak versioning
- Brak signed URLs (bezpieczne udostępnianie czasowe klientom)
- Brak CDN
- Wszystko na dysku hosta — przy padzie Hetzner = ryzyko utraty

Supabase Storage = S3 + CDN + signed URLs + integracja z RLS. To konkretna wygrana.

### 3.4 Off-my-hands ops

- Zero `alembic upgrade head` przy deployu (Supabase CLI + migracje)
- Zero martwienia się o PG upgrade
- Zero myślenia o backup retention
- Dashboard dla klienta/managera do ad-hoc queries bez dawania shella

### 3.5 Ścieżka do przyszłych feature'ów

Jeśli w przyszłości planujesz:
- **Portal kandydata** (self-service aplikacji) → Supabase Auth + RLS = dzień pracy zamiast tygodnia
- **Client portal** (klient widzi swoje kontraktory) → RLS zrobi to czysto
- **Multi-tenant** (gdybyś sprzedawał ATS jako SaaS) → Supabase jest naturalnym fundamentem

---

## 4. Argumenty PRZECIW — również konkretnie

### 4.1 Koszt migracji w pracy

| Zadanie | Szacunek |
|---|---|
| Migracja schematu (10 migracji → Supabase, zachowanie ID, sekwencji) | 1–2 dni |
| Migracja danych (seed → real data; `pg_dump` / `pg_restore`) | 0,5 dnia |
| Migracja userów + haseł (bcrypt niekompatybilny z GoTrue — users muszą zresetować) | 1 dzień + komunikacja |
| Przepisanie auth w backendzie (walidacja JWT Supabase, usunięcie `security.py`, `auth.py`) | 1–2 dni |
| Przepisanie auth we frontendzie (`@supabase/supabase-js`, Zustand → context Supabase) | 1–2 dni |
| Napisanie RLS policies (25 tabel × average 4 policies = 100 policies) | 2–3 dni |
| Przepisanie `ws.py` → Supabase Realtime (albo zostawienie custom z walidacją Supabase JWT) | 1 dzień |
| Migracja Storage (CV files) | 0,5 dnia |
| E2E: test każdego endpointu per rola | 2 dni |
| Redeploy: Coolify (tylko backend/frontend) + nowe env vars + CORS + redirect URLs | 0,5 dnia |
| **Razem** | **11–15 dni roboczych** |

Obecny plan RBAC: **1 dzień**.

### 4.2 Koszt finansowy — realna kalkulacja

**Supabase Free:**
- 500 MB DB, 5 GB egress, 1 GB storage, 50k MAU, 2 projekty
- Brak EU region (dane w US/UK/AP)
- Brak PITR
- Projekty pauzowane po 7 dniach nieaktywności

**Supabase Pro ($25/mo):**
- 8 GB DB (dalej $0.125/GB), 250 GB egress, 100 GB storage
- EU region dostępny
- PITR 7 dni, daily backup
- Compute add-ons: $10–60/mo za większe CPU/RAM (dla AI workload prawdopodobnie potrzebne)

**Realistyczna estymacja po roku używania:**
- ~2 GB Postgres (kandydaci + aktywności + notatki + screenings)
- ~5 GB Storage (CV, screenshots z Fireflies)
- ~50 GB egress/mo (frontend + API + Realtime)
- Compute: prawdopodobnie default (Tiny)
- **Realne: $25–40/mo = $300–480/rok**

**Hetzner dziś:**
- CX11 (1 vCPU, 2 GB RAM, 40 GB SSD) — €4,5/mo = ~$60/rok
- CX21 (2 vCPU, 4 GB RAM, 40 GB SSD) z headroom — €6,5/mo = ~$85/rok
- Backupy Hetzner Storage Box 100GB — €3/mo = ~$40/rok
- **Realne: ~$100–130/rok**

**Różnica: $200–350/rok na rzecz Hetzner.** W skali firmy to szum, ale **3–5× droższe** to 3–5× droższe.

### 4.3 Vendor lock-in — realny, skalujący się z czasem

Teraz (przed migracją): **zero couplingu**. Exit cost = 0.

Po migracji będziesz sprzężony w 5 wymiarach:
1. **Auth tokeny** — RLS policies zakładają format JWT Supabase (`auth.uid()`, `auth.jwt()`)
2. **Storage URLs** — linki do CV są Supabase-specific
3. **Realtime subscriptions** — klient używa `supabase-js`
4. **Edge Functions** (jeśli użyjesz) — Deno + specyficzne API
5. **Dashboard workflow** — team przyzwyczaja się do UI

Exit w roku 2: trzeba przepisać wszystkie 5 warstw. **Exit cost rośnie miesięcznie.** To nie jest teoretyczne ryzyko — historycznie Firebase, Parse, Heroku pokazały, że lock-in boli przy zmianie kierunku firmy.

### 4.4 Sunk cost Fazy 7d — namacalny

Tydzień pracy na:
- **Backup drill** → zbędny (Supabase PITR)
- **Auto-deploy webhook Coolify** → zbędny (Vercel/inny deploy pipeline)
- **Backend integration tests** → wymagają przepisania pod Supabase test project
- **Frontend Vitest + Playwright** → większość zostaje, ale testy auth/RBAC trzeba od nowa

Szacuję, że **30–40% pracy Fazy 7d idzie do kosza** przy migracji.

### 4.5 Custom backend features — nie wszystko mapuje się czysto

| Feature | Supabase-native? | Praca migracyjna |
|---|---|---|
| `ws.py` notifications | Częściowo — Realtime jest DB-driven, twoje broadcasts są event-driven | Zostaw własny WS + waliduj Supabase JWT (prościej) lub przepisz pod tabelę `notifications` z triggerami |
| `match_history_ttl` task | `pg_cron` w Supabase | Prosto — 1h |
| `slack_sla_alerts` | `pg_cron` + Edge Function | Średnio — 2h |
| Voyage AI embeddings | Bez zmian | 0 |
| Qdrant (wektory kandydatów) | **pgvector** w Supabase jako opcja | Migracja + benchmark. pgvector dla 1024-dim × 10k rekordów jest wolniejszy od Qdrant. Albo zostaw Qdrant self-hosted |
| Ollama lokalny LLM | Zostaje na Hetzner lub gdziekolwiek | 0 |
| Fireflies sync | Edge Function albo zostaje w FastAPI | 0–1 dzień |
| AI Prep Kit / AI Profile | Server-side heavy — Edge Function limity 150 MB memory, 2 min wykonania | **Pewnie zostaje w FastAPI** |

**Wniosek:** skończysz z **hybrydową architekturą** (Supabase + FastAPI na Hetzner dla AI) — więcej ruchomych części, nie mniej.

### 4.6 Skala jest za mała na wygrane Supabase

Wielkie wygrane Supabase (MFA, OAuth, Realtime, RLS) błyszczą w:
- Aplikacjach B2C z setkami tysięcy MAU
- Produktach, gdzie user-facing auth to core UX
- Zespołach frontendowych bez backendowców

Twój przypadek:
- **10–15 wewnętrznych użytkowników**
- **Zero external users** (brak portalu kandydata/klienta)
- **Masz backend developera** (w tym mnie)
- **Masz dojrzały FastAPI z 36 routerami**

**Prawdziwa stopa zwrotu Supabase jest niska** — bo nie wykorzystujesz 70% tego, za co płacisz.

### 4.7 Ryzyko tranzycyjne

- Migracja danych produkcyjnych = **ryzyko utraty lub desynchronizacji**
- 11–15 dni to okno, w którym system będzie w niestabilnym stanie — równolegle utrzymujesz dwa systemy albo masz downtime
- Zespół musi się uczyć nowego deploy flow, nowego dashboardu, nowego debug workflow
- Błąd w RLS policy = **wyciek danych między rolami** (trudniejszy do wykrycia niż missing `Depends(TacPlus)`)

### 4.8 Dane — EU region na Free nie ma

- **Free tier: US/UK/AP only**. Dane kandydatów (imię, nazwisko, email, telefon, CV) wychodzą poza EU.
- Pamięć mówi „bez GDPR" → formalnie nie przeszkadza, ale Twoi **klienci** body-leasingu mogą mieć GDPR w swoich kontraktach i zapytać gdzie są dane ich kandydatów.
- **EU region = Pro ($25/mo minimum)** → kasuje Free-tier argument.

---

## 5. Scenariusze hybrydowe (do rozważenia)

### Opcja A — tylko Supabase Auth, reszta zostaje

- Używasz **Supabase Auth (GoTrue) jako SaaS** — frontend autentykuje przez supabase-js, backend FastAPI waliduje JWT przez JWKS
- Reszta (DB, Qdrant, ws.py, Coolify) bez zmian
- **Zyskujesz:** reset hasła, OAuth, MFA
- **Tracisz:** niezależność auth (Supabase down → nikt się nie loguje); cena za MAU po przekroczeniu 100k (u Ciebie nigdy)
- **Praca:** 3–4 dni

### Opcja B — Supabase jako thin DB layer, FastAPI jako API

- Migrujesz Postgres do Supabase, ale **nie używasz RLS** — FastAPI dalej pilnuje autoryzacji
- Używasz Storage dla CV
- **Zyskujesz:** managed Postgres, Storage, dashboard
- **Tracisz:** RLS elegance (płacisz ale nie używasz core value)
- **Praca:** 4–5 dni
- **Uwaga:** to „najgorsze z obu światów" — płacisz vendor premium za benefity, które sam dostarczasz

### Opcja C — pełna migracja jak w sekcji 4.1

- Wszystko w Supabase, RLS, Realtime, Storage, Edge Functions
- Praca: 11–15 dni
- Maksymalne benefity, maksymalny lock-in

---

## 6. Macierz decyzyjna (ważona)

| Kryterium | Waga | Self-hosted | Supabase Auth only | Full Supabase |
|---|:---:|:---:|:---:|:---:|
| Koszt pracy migracji (odwrotnie) | 5 | 10 | 7 | 3 |
| Koszt miesięczny (odwrotnie) | 2 | 9 | 7 | 5 |
| Funkcje auth (reset, OAuth, MFA) | 3 | 3 | 9 | 9 |
| RLS/RBAC elegance | 3 | 6 | 6 | 9 |
| Lock-in (odwrotnie) | 4 | 10 | 7 | 3 |
| Ops mental load (odwrotnie) | 3 | 5 | 6 | 8 |
| Storage dla CV | 2 | 4 | 4 | 9 |
| Dopasowanie do skali (10–15 users) | 4 | 9 | 8 | 4 |
| Ryzyko migracji (odwrotnie) | 4 | 10 | 7 | 3 |
| Zgodność z Fazą 7d (sunk cost) | 3 | 10 | 8 | 4 |
| **Ważony wynik** | | **263** | **226** | **165** |

**Metodologia:** każde kryterium 1–10, mnożone przez wagę. „(odwrotnie)" = 10 to najlepiej dla danego kierunku (np. „koszt pracy odwrotnie: 10" = najtańsza praca).

---

## 7. Rekomendacja

### Preferowana: **Self-hosted, dokończ RBAC (~1 dzień)**

**Dlaczego:**
1. Obecne bolączki (brak route protection, messy dual role system) są rozwiązane w **1 dniu** zamiast 11–15
2. Skala 10–15 userów wewnętrznych **nie wymaga** wygranej Supabase Auth w perspektywie 12 miesięcy
3. Faza 7d dała **production-grade ops** na Hetzner — rezygnacja z tego teraz to pure throwaway
4. Lock-in **rośnie z czasem** — czekanie kosztuje mniej niż przedwczesna migracja
5. Masz **hybrydowy AI backend** (Voyage + Qdrant + Ollama + FastAPI) — Supabase nie zastąpi tego i skończysz z dwoma infrastrukturami

### Trigger do przemyślenia Supabase w przyszłości

Migrację rozważ, gdy **co najmniej dwa** z poniższych są prawdziwe:
- [ ] Budujesz portal kandydata (external users > 100)
- [ ] Budujesz portal klienta z self-service
- [ ] Masz > 20 wewnętrznych userów i resety hasła stają się tygodniowym bólem
- [ ] Planujesz sprzedaż ATS jako SaaS (multi-tenant)
- [ ] Hetzner przestaje spełniać wymagania skalowania
- [ ] Klient/audyt wymaga SOC2 / formalnej polityki backupów/MFA

### Jeśli koniecznie chcesz wygranej z Supabase teraz

**Opcja A (tylko Auth)** — 3–4 dni pracy, niski lock-in (Auth jest przenośny do GoTrue self-hosted lub innych providerów). Zostawia DB/backend/Qdrant na Hetzner. Największy ROI: self-service reset hasła + OAuth LinkedIn. **Kompromis, który ma sens.**

### Nie rekomenduję

**Opcja B (DB w Supabase bez RLS)** — płacisz vendor premium, nic nie zyskujesz. Antypattern.

---

## 8. Pytania do decyzji — jeśli waha Cię Opcja A

1. Czy Wy (Ty, Olaf, Marta, Tomasz, Dominik) logujecie się **minimum raz dziennie**? — tak → JWT 8h zostaje bezproblemowy; reset jest raz na kwartał
2. Czy **OAuth LinkedIn** to realny feature, czy nice-to-have?
3. Jak często robisz ręczne resety hasła? — jeśli ≥ 1x/mies, self-service ma sens
4. Czy planujesz w ciągu 12 m-cy dać dostęp osobom spoza firmy (klientom, kontraktorom)?

---

## 9. Rekomendowane następne kroki

1. **Dziś:** zdecyduj — self-hosted RBAC, Supabase Auth only, czy full migration. Jeśli niepewny, wybierz self-hosted (najniższe koszty odwrócenia decyzji).
2. **Teraz:** kontynuacja obecnego planu RBAC (model już zmigrowany do 6 ról, zostało 8 kroków na ~1 dzień pracy).
3. **Za 3 miesiące:** review — ile resetów hasła, czy ktoś płakał o OAuth, czy klienci pytali o GDPR. Wtedy trigger z sekcji 7 decyduje.
4. **Za 6 miesięcy:** jeśli Opcja A wygląda atrakcyjnie, migracja auth (3–4 dni, niski risk).

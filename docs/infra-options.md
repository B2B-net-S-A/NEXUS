# NEXUS — opcje infrastruktury (po awarii 2026-07-17)

> Decyzyjny przegląd: jak zmniejszyć ryzyko awarii typu „cała firma leży", biorąc pod
> uwagę, że **jedynym devem/ops jest Claude Code** (brak ludzkiego zespołu ops).
> Kontekst awarii i recipe naprawy: `docs/` + pamięć projektu.

## Co się właściwie zepsuło (żeby dobrać właściwy fix)

Awaria **nie była w bazie danych.** Postgres działał, dane były bezpieczne. Padła
warstwa **compute / build / deploy** na jednym serwerze:

1. Dysk serwera zapełnił się do **98,8%** — śmieci po nieudanych buildach Coolify.
2. Postgres i Coolify nie miały gdzie pisać → crash-loop → backend i panel down.
3. Recovery był trudny, bo to **self-hosted single-server** (Hetzner + Coolify): brak
   managed auto-recovery, dostęp tylko przez połamaną konsolę, wszystko ręcznie.

**Wniosek:** ryzyko siedzi w *samodzielnie zarządzanej warstwie aplikacji/deployu i we
współdzielonym dysku*, nie w silniku bazy. Dlatego **sam Supabase (managed Postgres) by
tego nie zatrzymał** — Compass i Atlas już używają Supabase na bazę, a i tak stoją na tym
samym Coolify i mogą paść identycznie.

## Warstwy i gdzie każda opcja pomaga

| Warstwa | Dziś | Padło dziś? | Co naprawia |
|---|---|---|---|
| Baza (Postgres) | self-hosted kontener | nie | Managed Postgres (Supabase/Neon) |
| Wektory (Qdrant) | self-hosted kontener | nie | Qdrant Cloud (opcjonalnie) |
| Backend (FastAPI) | kontener na Coolify | **tak** (crash-loop) | Managed hosting (Railway/Render/Fly) |
| Frontend (Next.js) | kontener na Coolify | częściowo | Vercel / managed hosting |
| Build/deploy (Coolify) | self-hosted PaaS | **tak** (queue jam, 500) | Managed hosting / hardening |
| Dysk hosta | 1× 75 GB współdzielony | **tak** (98,8%) | Alert + higiena + separacja bazy |

## Rekomendacja: 3 kroki, od najtańszego

### Krok 0 — Alerty + higiena dysku ⟵ ZRÓB NAJPIERW (zrobione / w toku)
- **Alert na dysk** (`>=75%`) — wdrożony: `/api/health` wystawia `diskPercent`,
  a `.github/workflows/disk-alert.yml` co godzinę alarmuje (issue + mail).
  **To jedno by dzisiejszej awarii zapobiegło** (ostrzeżenie na dni przed).
- Coolify ma już `force_docker_cleanup` (próg 80%, codziennie) — zostaje jako druga linia.
- Koszt: **0 zł**. Ryzyko: zerowe. Efekt: łapiemy problem, zanim położy firmę.

### Krok 1 — Baza → managed Postgres (Supabase lub Neon)
- **Co daje:** koniec z samodzielnym Postgresem — automatyczne backupy, PITR, osobny
  dysk/skalowanie, baza **odseparowana** od serwera aplikacji (pełny dysk hosta już jej
  nie zabija). Tu Supabase realnie pomaga.
- **Nakład:** średni — zmiana `DATABASE_URL` + migracja danych (`pg_dump`/`pg_restore`),
  test migracji Alembic na nowej bazie, sprawdzenie latencji (baza w tym samym regionie:
  Frankfurt). Qdrant zostaje osobno.
- **Ryzyko:** średnie — migracja danych to operacja jednorazowa; zrobić w oknie, z backupem.
- **Supabase vs Neon:** Supabase = Postgres + Auth + Storage + Edge Functions (więcej,
  spójne z Compass/Atlas). Neon = „czysty" serverless Postgres, tańszy, auto-scale, branching
  — jeśli chcesz *tylko* bazę bez reszty platformy. Dla spójności z resztą stacku: **Supabase**.
- **Koszt:** Supabase Pro ~25 USD/mies. / Neon od darmowego, płatny ~19 USD/mies.

### Krok 2 — Hosting aplikacji → managed PaaS (Railway / Render / Fly.io)
- **Co daje:** to jest warstwa, która **dziś padła**. Managed PaaS sam ogarnia buildy,
  dysk (osobny per-serwis, auto), restarty, health-recovery, rollbacki — **znika Coolify
  jako punkt awarii** i znika „ręczne SSH w kryzysie".
- **Nakład:** największy — przeniesienie backendu FastAPI + frontendu + Qdrant, przepięcie
  env/secretów, CI/CD, domeny. Ale bez przepisywania kodu (to nadal te same kontenery).
- **Ryzyko:** średnie/wysokie — dużo ruchomych części, robić etapami (najpierw jeden serwis).
- **Koszt:** Railway/Render ~5–20 USD/serwis/mies.; Fly.io podobnie. Droższe niż własny
  Hetzner, ale kupujesz **brak nocnych pożarów**.
- **Alternatywa (tańsza):** zostać na Coolify, ale **utwardzić**: osobny build-cache z limitem,
  cron `docker image/builder prune`, monitoring+alerty (Krok 0), zakaz `container prune`,
  backup coolify-db. Mniej pracy, ale ryzyko operacyjne zostaje wyższe niż na managed.

## Czego NIE robić
- **Nie przepisywać backendu FastAPI na Supabase Edge Functions** — matching, scoring,
  Qdrant, 14 background-tasków, integracje (Traffit/CloudTalk/M365) to duży, długo działający
  Python; Edge Functions (Deno, krótkie) się do tego nie nadają. Ogromny rewrite, niewarty.
- **Nie migrować pod wpływem jednej awarii, wszystkiego naraz.** Solo-dev = rób małymi,
  odwracalnymi krokami; każdy z osobnym oknem i backupem.

## Sugerowana kolejność decyzji
1. ✅ **Krok 0** (alerty + higiena) — zrobione, koszt 0.
2. **Krok 1** (managed Postgres) — gdy zdecydujesz; największy zysk odporności / nakład.
3. **Krok 2** (managed hosting) — dopiero jeśli po Kroku 0+1 dalej boli operacyjnie.

> Sam Krok 0 zamienia „firma leży 3h, ratujemy ręcznie" w „mail: dysk 75%, sprzątam zdalnie
> jednym poleceniem". Reszta to zmniejszanie *powierzchni* rzeczy, które w ogóle mogą paść.

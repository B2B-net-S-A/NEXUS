# Deploy

- **Hosting:** Coolify v4 self-hosted on Hetzner **CCX33 x86** (8 vCPU / 32 GB, 91.99.199.112). Zweryfikowane w konsoli Hetznera 20.07.2026 — wcześniejszy wpis „CAX21 ARM" był błędny i wysłał audyt 13.09 w niepotrzebne zastrzeżenia o typie hosta.
- **Coolify panel:** `https://coolify-nexus.dynaminds.pl` (HTTPS+LE, public via Traefik route — od 2026-05-04).
- **App UUID (Coolify):** `ocgkwcbovpve9wvf9smxl0kx`.
- **Registry:** **brak GHCR** — Coolify buduje obrazy lokalnie z compose `build:` block (jednolite z Compass + LeadGen).
- **Compose orkiestracja:**
  - `docker-compose.yml` — base z `build:` block (no port bindings, Coolify Traefik routuje przez `expose:`). **Limity pamięci (mem_limit) są TUTAJ** — Coolify czyta wyłącznie ten plik (docker_compose_location), więc limity trzymane w overlayu nigdy nie obowiązywały na prodzie (Memory=0, wykryte i naprawione 2026-08-12).
  - `docker-compose.override.yml` — dev (re-adds host port bindings, auto-loaded przez `docker compose up`).
  - `docker-compose.prod.yml` — prod overlay (ports/env/healthchecks — referencja do ręcznej symulacji prod; BEZ limitów zasobów).
- **Auto-deploy:** ✅ **TAK** — `git push origin main` → `.github/workflows/deploy.yml` (unified template, PR #68 merged 2026-05-04) → Coolify webhook → build + restart → smoke test.
- **Trigger:** push `main` → `.github/workflows/deploy.yml`.
- **Na produkcję wchodzi tylko commit z zieloną bramką (DEP-01, od 15.09.2026).**
  Coolify 4.1.2 buduje ZAWSZE HEAD maina — ignoruje nawet przypięty
  `git_commit_sha` (`check_git_if_build_needed` nadpisuje go `git ls-remote`;
  poprawione w 4.2.0), więc przypinanie nic nie daje. Zamiast tego
  `.github/scripts/select_release_sha.py`: job `select` puszcza deploy tylko
  przy zielonym „CI Gate” HEAD maina (bramka w toku = odroczenie, wdroży go
  jego własny przebieg; czerwona = wstrzymanie z ostrzeżeniem, ręczny dispatch =
  błąd), a smoke przyjmuje RELEASE_SHA albo jego POTOMKA z zieloną bramką
  (merge w trakcie budowy, czeka ≤ 10 min na bramkę w toku). Potomek z czerwoną
  bramką = czerwony deploy z instrukcją wycofania. Czerwony HEAD maina
  wstrzymuje deploye do następnego zielonego commitu — to zamierzone. Zmiana
  bramki deployu z „CI Gate” na „CI” wymaga zmiany `GATE_WORKFLOW` w skrypcie.
- **Rollback:** Coolify panel `https://coolify-nexus.dynaminds.pl` → Resources → nexus → Deployments → poprzedni → Redeploy.
- **Standardy + procedury:** patrz `~/.claude/rules/deployment.md` + `~/.claude/rules/deployment-runbook.md`.

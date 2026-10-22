# Deploy

- **Hosting:** Coolify v4 self-hosted on Hetzner **CCX33 x86** (8 vCPU / 32 GB, 91.99.199.112). Zweryfikowane w konsoli Hetznera 20.07.2026 — wcześniejszy wpis „CAX21 ARM" był błędny i wysłał audyt 13.09 w niepotrzebne zastrzeżenia o typie hosta.
- **Coolify panel:** `https://coolify-nexus.dynaminds.pl` (HTTPS+LE, public via Traefik route — od 2026-05-04).
- **App UUID (Coolify):** `ocgkwcbovpve9wvf9smxl0kx`.
- **Registry:** **brak GHCR** — Coolify buduje obrazy lokalnie z compose `build:` block (jednolite z Compass + LeadGen).
- **Compose orkiestracja:**
  - `docker-compose.yml` — base z `build:` block (no port bindings, Coolify Traefik routuje przez `expose:`). **Limity pamięci (mem_limit) są TUTAJ** — Coolify czyta wyłącznie ten plik (docker_compose_location), więc limity trzymane w overlayu nigdy nie obowiązywały na prodzie (Memory=0, wykryte i naprawione 2026-08-12).
  - `docker-compose.override.yml` — dev (re-adds host port bindings, auto-loaded przez `docker compose up`).
  - `docker-compose.prod.yml` — prod overlay (ports/env/healthchecks — referencja do ręcznej symulacji prod; BEZ limitów zasobów).
- **Auto-deploy:** ✅ **TAK, pon–pt w oknie 18:00–08:00 (Europe/Warsaw, decyzja Artura 14.10.2026, godziny 18:00–08:00 od 22.10.2026), w sobotę i niedzielę o każdej porze (17.10.2026)** — `git push origin main` → „CI Gate” → `.github/workflows/deploy.yml` (unified template, PR #68 merged 2026-05-04) → w dzień roboczy odroczenie `night_freeze`, wieczorem budzik `deploy-window` (19:05/21:05/23:05, zapasowo cron GitHuba) → API Coolify (POST `/api/v1/deploy`) → build + restart → smoke test. Szczegóły okna, tryb `emergency` (tylko na polecenie Artura) i alarm „noc bez wdrożenia”: `ci-gotchas.md`.
- **Trigger:** push `main` → `.github/workflows/deploy.yml`. Coolify NIE buduje sam po pushu: webhook GitHuba do Coolify wyłączony 14.10.2026 (i tak nie dochodził — port 8000 zamknięty), a `coolify_release_audit.py` (`coolify-ops.yml`, akcja `release-config-audit`) pada przy włączonym Auto Deploy aplikacji.
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
- **Jeden rebuild na zmianę, także przy „Coolify set env” (18.10.2026).**
  18.10 ok. 15:30 użytkownicy mieli dwie przerwy (~15:30–15:34 i ~15:36–15:40)
  przez dwa Deploye tego samego commitu 1644e9e30: merge #2313 (sam `docs/`)
  przebudował produkcję, a ręczny Deploy po dwóch „Coolify set env”
  (`redeploy=false`) czekał w kolejce za nim i przebudował ją drugi raz, bo
  ręczny bieg nigdy nie pomijał rebuildu. Od tej poprawki krok koalescencji
  w `deploy.yml` (`.github/scripts/deploy_needed.py`) pomija rebuild w KAŻDYM
  biegu — automatycznym i ręcznym — gdy od wersji z `/api/health` nie zmienił
  się kod obrazu (zmiany wyłącznie w `docs/`, `*.md` w korzeniu repo,
  `.github/workflows/`, `.github/scripts/tests/`) i żadna zmienna w Coolify
  (`updated_at`) nie jest nowsza niż start kroku „Trigger deployment”
  w ostatnim udanym Deployu. Coolify robi zrzut zmiennych na początku
  wdrożenia, więc zmienna ustawiona w trakcie budowy wymusza następny rebuild —
  i on się odbędzie. Skutki:
  - Kilka zmiennych: ustaw wszystkie z `redeploy=false`, potem JEDEN Deploy
    (albo ostatni set env z `redeploy=true`). Deploy uruchomiony po wdrożeniu,
    które zmienne już zabrało, kończy się na kroku koalescencji bez przerwy.
  - Zmienne przed merge'em, nie zaraz po nim: wtedy deploy merge'a zabiera je
    od razu. Zmiana zmiennej w trakcie budowy = dwie przerwy (nie da się tego
    uniknąć bez przerywania wdrożenia w Coolify).
  - Po merge'u samych dokumentów `/api/health` dalej pokazuje poprzedni SHA —
    to nie zaległe wdrożenie. DoD: produkcja ma ostatni commit, który zmienia
    kod obrazu (`git diff --stat <live>..origin/main`).
  - Rebuild mimo braku zmian (zawieszony kontener, usunięta zmienna — usunięcia
    `updated_at` nie widzi): Deploy z `force_rebuild=true`, który pomija to
    sprawdzenie. Okno wdrożeń i `emergency` działają jak dotąd.
  - Brak odczytu zmiennych z API Coolify: bieg automatyczny pomija rebuild
    tylko przy tym samym kodzie (jak przed 18.10), ręczny wdraża. Każdy inny
    błąd sprawdzenia = wdrożenie.
- **Rollback:** Coolify panel `https://coolify-nexus.dynaminds.pl` → Resources → nexus → Deployments → poprzedni → Redeploy. W dzień roboczy (pon–pt 08:00–18:00) tylko na polecenie Artura — to też przebudowa z przerwą; w weekend bez ograniczeń.
- **Standardy + procedury:** patrz `~/.claude/rules/deployment.md` + `~/.claude/rules/deployment-runbook.md`.

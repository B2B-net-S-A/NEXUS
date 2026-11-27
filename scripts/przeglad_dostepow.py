#!/usr/bin/env python3
"""Kwartalny przegląd dostępów NEXUSA: wypisuje konta, klucze i tokeny, niczego nie zmienia.

    python3 scripts/przeglad_dostepow.py            # wszystko (GitHub + serwer + NEXUS)
    python3 scripts/przeglad_dostepow.py --bez-ssh  # tylko GitHub

Źródła:
- GitHub przez ``gh api`` (organizacja i repo NEXUS): wymóg 2FA, członkowie bez 2FA,
  współpracownicy, klucze wdrożeniowe, nazwy sekretów repo z datą zmiany;
- serwer przez SSH z konfiguracji ``scripts/prod_readonly.py``
  (``~/.claude/nexus-rutyny/prod-readonly.conf``): odciski kluczy w
  ``/root/.ssh/authorized_keys``, konta panelu Coolify z flagą 2FA, tokeny API
  Coolify (id, nazwa, ostatnie użycie — bez wartości), aktywne konta NEXUSA
  (rola, SSO, hasło, ostatnia aktywność), lista break-glass zamaskowana.

Bazy czyta w transakcji ``READ ONLY``. Entra, Cloudflare, Hetzner, Grafana Cloud
i Sentry nie mają tu dostępu bez logowania — lista na końcu wyjścia mówi, co
sprawdzić ręcznie. Procedura: ``docs/claude/podstawy/dostepy-onboarding-offboarding.md``.

Wyjście zawiera adresy e-mail: tylko terminal, nigdy repo, PR ani logi Actions
(repo i Actions są publiczne).

Python 3.9 (systemowy na laptopie), bez zależności spoza biblioteki standardowej.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

REPO = os.environ.get("NEXUS_GH_REPO", "B2B-net-S-A/NEXUS")
ORG = REPO.split("/", 1)[0]

# Progi przeglądu: po tylu dniach bez użycia wpis idzie na listę „do decyzji”.
STALE_ACCOUNT_DAYS = 30
STALE_TOKEN_DAYS = 30
STALE_DEPLOY_KEY_DAYS = 90

# Rola konta testów E2E: hasło bez SSO to jej normalny stan (podstawy/konto-e2e-na-produkcji.md).
PASSWORD_ROLES_OK = {"automation"}

SECTION = "##"

# Jedna stała komenda na serwerze. Każda sekcja zaczyna się od znacznika ``##NAZWA``.
# Psql w trybie -At z separatorem ``|``; tokeny i hasła nigdy nie są wybierane.
REMOTE_COMMAND = (
    "set -u; "
    "echo '##KEYS'; ssh-keygen -lf /root/.ssh/authorized_keys; "
    "echo '##COOLIFY_USERS'; "
    "docker exec coolify-db psql -U coolify -d coolify -At -F '|' -c "
    '"SET default_transaction_read_only = on; '
    "SELECT u.id, u.email, (u.two_factor_confirmed_at IS NOT NULL), "
    "coalesce(string_agg(tu.role, ','), '') FROM users u "
    'LEFT JOIN team_user tu ON tu.user_id = u.id GROUP BY 1, 2, 3 ORDER BY 1;" '
    "< /dev/null | grep -v '^SET$'; "
    "echo '##COOLIFY_TOKENS'; "
    "docker exec coolify-db psql -U coolify -d coolify -At -F '|' -c "
    '"SET default_transaction_read_only = on; '
    "SELECT id, name, tokenable_id, coalesce(last_used_at::date::text, ''), "
    "coalesce(expires_at::date::text, '') FROM personal_access_tokens ORDER BY id;\" "
    "< /dev/null | grep -v '^SET$'; "
    "echo '##NEXUS_USERS'; "
    "p=$(docker ps --format '{{.Names}}' | grep '^postgres-ocgkw' | head -1); "
    "docker exec \"$p\" psql -U nexus -d nexus -At -F '|' -c "
    '"SET default_transaction_read_only = on; '
    "SELECT id, email, role, (azure_oid IS NOT NULL), (password_hash IS NOT NULL), "
    "coalesce(last_seen_at::date::text, '') FROM users WHERE is_active ORDER BY role, id;\" "
    "< /dev/null | grep -v '^SET$'; "
    "echo '##BREAK_GLASS'; "
)


def _load_prod_readonly():
    """Konfiguracja SSH i komenda szukania kontenera web z ``prod_readonly.py`` (jedno źródło)."""
    path = Path(__file__).with_name("prod_readonly.py")
    spec = importlib.util.spec_from_file_location("prod_readonly", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("prod_readonly", module)
    spec.loader.exec_module(module)
    return module


def remote_command(find_web_container: str) -> str:
    """Lista break-glass z procesu 1 backendu, zamaskowana na serwerze (``abc…@domena``)."""
    return (
        REMOTE_COMMAND
        + find_web_container
        + (
            "pid=$(docker inspect -f '{{.State.Pid}}' \"$c\"); "
            "tr '\\0' '\\n' < \"/proc/$pid/environ\" "
            "| sed -n 's/^PASSWORD_LOGIN_BREAK_GLASS_EMAILS=//p' | tr ',' '\\n' "
            "| sed -E 's/^ *([^@]{1,3})[^@]*@/\\1…@/' | grep -v '^$'; true"
        )
    )


# --- parsowanie --------------------------------------------------------------


def split_sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    for raw in output.splitlines():
        line = raw.rstrip()
        if line.startswith(SECTION):
            current = line[len(SECTION) :]
            sections[current] = []
        elif current is not None and line:
            sections[current].append(line)
    return sections


def _days_since(value: str, today: date) -> Optional[int]:
    if not value:
        return None
    return (today - date.fromisoformat(value[:10])).days


@dataclass(frozen=True)
class Finding:
    area: str
    text: str


def review_keys(lines: Sequence[str]) -> tuple[list[str], list[Finding]]:
    rows, findings = [], []
    for line in lines:
        parts = line.split(None, 2)  # bity, odcisk, „komentarz (TYP)”
        if len(parts) < 3:
            continue
        comment = parts[2].rsplit(" (", 1)[0]
        rows.append(f"{parts[1]}  {comment}")
        if comment == "no comment":
            findings.append(
                Finding(
                    "SSH",
                    f"klucz {parts[1][:20]}… bez komentarza: ustal właściciela albo usuń",
                )
            )
    return rows, findings


def review_coolify_users(lines: Sequence[str]) -> tuple[list[str], list[Finding]]:
    rows, findings = [], []
    for line in lines:
        uid, email, tfa, roles = (line.split("|") + ["", "", "", ""])[:4]
        rows.append(
            f"konto {uid}: {email}  rola={roles or '-'}  2FA={'tak' if tfa == 't' else 'NIE'}"
        )
        if tfa != "t":
            findings.append(
                Finding("Coolify", f"konto {uid} bez 2FA (Profile → Two-factor)")
            )
    return rows, findings


def review_coolify_tokens(
    lines: Sequence[str], today: date
) -> tuple[list[str], list[Finding]]:
    rows, findings = [], []
    for line in lines:
        tid, name, owner, last_used, expires = (line.split("|") + [""] * 5)[:5]
        idle = _days_since(last_used, today)
        rows.append(
            f"token {tid} „{name}” konta {owner}: ostatnio {last_used or 'nigdy'}"
            f", wygasa {expires or 'nigdy'}"
        )
        if idle is None:
            findings.append(
                Finding(
                    "Coolify",
                    f"token {tid} „{name}” nigdy nieużyty: usuń, jeśli zbędny",
                )
            )
        elif idle > STALE_TOKEN_DAYS:
            findings.append(
                Finding(
                    "Coolify",
                    f"token {tid} „{name}” nieużywany {idle} dni: usuń, jeśli zbędny",
                )
            )
    return rows, findings


def review_nexus_users(
    lines: Sequence[str], today: date
) -> tuple[list[str], list[Finding]]:
    rows, findings = [], []
    for line in lines:
        uid, email, role, sso, has_pwd, last_seen = (line.split("|") + [""] * 6)[:6]
        idle = _days_since(last_seen, today)
        rows.append(
            f"{uid:>4} {role:<26} SSO={'tak' if sso == 't' else 'NIE'} "
            f"hasło={'tak' if has_pwd == 't' else 'nie'} ostatnio={last_seen or 'nigdy'}  {email}"
        )
        if role in PASSWORD_ROLES_OK:
            # Konto E2E loguje się hasłem z CI i nie zapisuje last_seen_at.
            continue
        if sso != "t":
            findings.append(
                Finding(
                    "NEXUS",
                    f"konto {uid} ({role}) aktywne bez SSO: sprawdź, czy potrzebne",
                )
            )
        if idle is None:
            findings.append(
                Finding("NEXUS", f"konto {uid} ({role}) nigdy nieużyte: wyłączyć?")
            )
        elif idle > STALE_ACCOUNT_DAYS:
            findings.append(
                Finding(
                    "NEXUS",
                    f"konto {uid} ({role}) bez aktywności {idle} dni: wyłączyć?",
                )
            )
    return rows, findings


def review_break_glass(lines: Sequence[str]) -> tuple[list[str], list[Finding]]:
    rows = [f"break-glass: {line}" for line in lines]
    findings = []
    if lines:
        findings.append(
            Finding(
                "NEXUS",
                f"{len(lines)} adres(y) z logowaniem hasłem mimo SSO-only (omija MFA Entra): "
                "każdy ma mieć długie, unikalne hasło w menedżerze haseł",
            )
        )
    return rows, findings


def review_github(data: dict, today: date) -> tuple[list[str], list[Finding]]:
    rows, findings = [], []
    org = data.get("org", {})
    rows.append(
        f"organizacja {ORG}: wymóg 2FA={'tak' if org.get('two_factor_requirement_enabled') else 'NIE'}"
    )
    if not org.get("two_factor_requirement_enabled"):
        findings.append(
            Finding(
                "GitHub",
                f"organizacja {ORG} nie wymaga 2FA (Settings → Authentication security)",
            )
        )
    rows.append("członkowie: " + ", ".join(data.get("members", [])))
    no_2fa = data.get("members_no_2fa", [])
    if no_2fa:
        findings.append(Finding("GitHub", "członkowie bez 2FA: " + ", ".join(no_2fa)))
    outside = data.get("outside", [])
    rows.append("współpracownicy spoza organizacji: " + (", ".join(outside) or "brak"))
    rows.append("dostęp do repo: " + ", ".join(data.get("collaborators", [])))
    for key in data.get("deploy_keys", []):
        idle = _days_since(key.get("last_used") or "", today)
        rows.append(
            f"klucz wdrożeniowy {key['id']} „{key['title']}” tylko-odczyt={key['read_only']}"
            f" ostatnio={key.get('last_used') or 'nigdy'}"
        )
        if idle is None or idle > STALE_DEPLOY_KEY_DAYS:
            findings.append(
                Finding(
                    "GitHub",
                    f"klucz wdrożeniowy {key['id']} nieużywany: usuń, jeśli zbędny",
                )
            )
        if not key.get("read_only"):
            findings.append(
                Finding("GitHub", f"klucz wdrożeniowy {key['id']} ma zapis do repo")
            )
    secrets = data.get("secrets", [])
    rows.append(f"sekrety repo: {len(secrets)} (nazwa, ostatnia zmiana):")
    rows.extend(f"  {s['name']}  {s['updated_at'][:10]}" for s in secrets)
    return rows, findings


# --- źródła ------------------------------------------------------------------


def _gh_pages(path: str) -> list:
    """Wszystkie strony odpowiedzi jako lista (``--paginate --slurp``); GH_TOKEN z env pomijany."""
    env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    proc = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", path],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh api {path}: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)


def _gh_list(path: str) -> list:
    return [item for page in _gh_pages(path) for item in page]


def fetch_github() -> dict:
    data: dict = {"org": _gh_pages(f"orgs/{ORG}")[0]}
    data["members"] = [m["login"] for m in _gh_list(f"orgs/{ORG}/members")]
    data["members_no_2fa"] = [
        m["login"] for m in _gh_list(f"orgs/{ORG}/members?filter=2fa_disabled")
    ]
    data["outside"] = [
        m["login"] for m in _gh_list(f"orgs/{ORG}/outside_collaborators")
    ]
    data["collaborators"] = [
        f"{c['login']} ({c.get('role_name', '?')})"
        for c in _gh_list(f"repos/{REPO}/collaborators")
    ]
    data["deploy_keys"] = _gh_list(f"repos/{REPO}/keys")
    data["secrets"] = [
        s
        for page in _gh_pages(f"repos/{REPO}/actions/secrets")
        for s in page.get("secrets", [])
    ]
    return data


MANUAL_CHECKS = [
    (
        "Entra",
        "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/AuthenticationMethodsMenuBlade/~/UserRegistrationDetails",
        "osoby bez metody MFA; konta osób, które odeszły, zablokowane",
    ),
    (
        "Entra",
        "https://entra.microsoft.com/#view/Microsoft_AAD_ConditionalAccess/ConditionalAccessBlade/~/Policies",
        "polityki MFA włączone; wykluczenia tylko konta awaryjne",
    ),
    (
        "Cloudflare",
        "https://dash.cloudflare.com/profile/authentication",
        "2FA konta; członkowie konta (Manage Account → Members)",
    ),
    (
        "Hetzner",
        "https://accounts.hetzner.com/",
        "2FA konta; członkowie projektu w Cloud Console → Security → Members; klucze SSH projektu",
    ),
    (
        "Grafana Cloud",
        "https://grafana.com/orgs",
        "członkowie organizacji; 2FA przez dostawcę logowania",
    ),
    (
        "Sentry",
        "https://sentry.io/settings/account/security/",
        "2FA konta; Organization → Members kolumna 2FA",
    ),
]


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if any(a != "--bez-ssh" for a in args):
        print("Jedyna opcja to --bez-ssh.", file=sys.stderr)
        return 2
    today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
    findings: list[Finding] = []
    exit_code = 0

    def show(title: str, rows: Sequence[str]) -> None:
        print(f"\n=== {title}")
        for row in rows:
            print(f"  {row}")

    try:
        rows, found = review_github(fetch_github(), today)
        show("GitHub", rows)
        findings += found
    except RuntimeError as exc:
        print(f"GitHub: {exc}", file=sys.stderr)
        exit_code = 1

    if "--bez-ssh" not in args:
        pr = _load_prod_readonly()
        proc = pr.ssh(remote_command(pr._FIND_WEB_CONTAINER), timeout=120)
        if proc.returncode != 0:
            print(
                f"Serwer: SSH zwrócił {proc.returncode}: {proc.stderr.strip()[:300]}",
                file=sys.stderr,
            )
            exit_code = 1
        sections = split_sections(proc.stdout)
        for title, (rows, found) in (
            ("Klucze SSH roota", review_keys(sections.get("KEYS", []))),
            (
                "Panel Coolify: konta",
                review_coolify_users(sections.get("COOLIFY_USERS", [])),
            ),
            (
                "Panel Coolify: tokeny API",
                review_coolify_tokens(sections.get("COOLIFY_TOKENS", []), today),
            ),
            (
                "NEXUS: aktywne konta",
                review_nexus_users(sections.get("NEXUS_USERS", []), today),
            ),
            (
                "NEXUS: logowanie hasłem (break-glass)",
                review_break_glass(sections.get("BREAK_GLASS", [])),
            ),
        ):
            show(title, rows)
            findings += found

    show("Do decyzji", [f"[{f.area}] {f.text}" for f in findings] or ["nic"])
    show(
        "Ręcznie (bez API)",
        [f"[{area}] {what}: {url}" for area, url, what in MANUAL_CHECKS],
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

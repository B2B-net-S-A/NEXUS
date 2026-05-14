# Microsoft Defender for Endpoint — Hetzner hosts runbook

Step-by-step onboarding of Hetzner servers (NEXUS, Compass, Atlas) into
Microsoft Defender for Endpoint via the M365 Security center. Linux daemon
`mdatp` runs on each host, reports back to `security.microsoft.com`.

Phase 7.9 of the M365 ecosystem expansion (plan `elegant-percolating-thimble`).

## License context

| Item | Value |
|---|---|
| SKU | Defender for Business servers (per-server) |
| Quantity owned | 4 licenses (Partner center) |
| Used | 3 (NEXUS, Compass, Atlas) + 1 spare |
| Renewal | 2027-02-10 |

Licenses activate at onboarding — the M365 portal auto-associates an available
license with each registered server. No manual binding required.

## Servers in scope

Architecture / OS verified via `ssh root@<ip> "lsb_release -d && uname -m"`
on 2026-05-14:

| App | Hostname / FQDN | IP | OS | Arch | Docker stack | Real-time protection |
|---|---|---|---|---|---|---|
| NEXUS (ATS) | `api.nexus.dynaminds.pl` | 91.99.199.112 | Ubuntu 24.04.4 LTS | `x86_64` | Coolify v4 + Postgres + Qdrant | ON (sensitive HR data) |
| Compass | `compass.dynaminds.pl` | 178.104.220.48 | Ubuntu 24.04.3 LTS | `aarch64` (Hetzner CAX21 ARM) | Coolify v4 + Supabase | ON (sensitive HR data) |
| Atlas (LeadGen) | `atlas.dynaminds.pl` | 78.47.89.127 | Ubuntu 24.04.4 LTS | `aarch64` (Hetzner CAX21 ARM, rescaled 2026-05-08) | Coolify v4 + Supabase | OFF (constrained resources — scheduled scans only) |

> **Note:** older internal references (`~/.claude/rules/deployment.md`) list
> NEXUS as CAX21 ARM. The live host is x86_64 — the rule is stale and will
> be reconciled separately. Both architectures are supported by `mdatp` on
> Linux (aarch64 support GA since June 2024).

Real-time protection decision: NEXUS and Compass hold candidate / HR personal
data, so the constant scan budget is worth the cost. Atlas was rescaled to
CAX21 ARM in May 2026 but its compose stack runs close to memory ceiling
(scheduler + web + Alloy sidecar at 256M), so we keep `mdatp` on quick + daily
scans only.

## Prerequisites

- Global Admin or Security Admin role in M365 tenant `b2bnetwork.pl`.
- Root SSH to all three hosts (keys under `~/.ssh/`).
- Linux distribution check before install:

  ```bash
  ssh root@91.99.199.112 "lsb_release -d"
  ssh root@178.104.220.48 "lsb_release -d"
  ssh root@78.47.89.127  "lsb_release -d"
  ```

  Supported Linux versions: Ubuntu 18.04+, Debian 9+, RHEL 7.2+, CentOS 7.2+,
  SLES 12+, Oracle Linux 7.2+. If a host shows an unsupported version, stop
  and upgrade the OS before continuing.

## 1. Generate the onboarding package (one-time)

Sign in to [security.microsoft.com](https://security.microsoft.com) as admin.

1. **Settings → Endpoints → Onboarding**.
2. **Select operating system**: `Linux Server`.
3. **Deployment method**: `Local script (for up to 10 devices)`.
4. **Download onboarding package** → `WindowsDefenderATPOnboardingPackage.zip`.

The same package onboards all three servers — it embeds the tenant's enrollment
secret. Re-download only if you rotate the secret (Settings → Endpoints →
Offboarding undoes a device; rotation is separate).

## 2. Install per server

Repeat the block below for each of the three servers. Example shown for NEXUS
(`91.99.199.112`); swap IP for Compass / Atlas.

### 2.1 Upload onboarding package

From your local mac:

```bash
scp ~/Downloads/WindowsDefenderATPOnboardingPackage.zip root@91.99.199.112:/tmp/
```

### 2.2 Add the Microsoft package repo

SSH into the server and configure the official Microsoft apt repo (Ubuntu
24.04, matches all three hosts as of 2026-05-14):

```bash
ssh root@91.99.199.112
curl -O https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb
dpkg -i packages-microsoft-prod.deb
rm packages-microsoft-prod.deb
apt-get update
```

The Microsoft repo serves both `amd64` (NEXUS) and `arm64` (Compass, Atlas)
from the same URL — `apt` picks the right architecture automatically. If a
host runs a different Ubuntu LTS, swap `24.04` for the version returned by
`lsb_release -r`; the [official install matrix](https://learn.microsoft.com/en-us/microsoft-365/security/defender-endpoint/linux-install-manually)
lists supported distros.

### 2.3 Install `mdatp`

```bash
apt-get install -y mdatp
```

### 2.4 Apply onboarding script

```bash
cd /tmp
unzip WindowsDefenderATPOnboardingPackage.zip
bash MicrosoftDefenderATPOnboardingLinuxServer.py
rm WindowsDefenderATPOnboardingPackage.zip MicrosoftDefenderATPOnboardingLinuxServer.py
```

### 2.5 Verify connection

```bash
mdatp health
```

Expected output (excerpt):

```
healthy                       : true
licensed                      : true
real_time_protection_enabled  : true     # NEXUS, Compass
real_time_protection_enabled  : false    # Atlas (set below)
definitions_updated           : 2026-...
```

If `healthy: false`, jump to [Troubleshooting](#troubleshooting).

## 3. Configure exclusions (Docker + Coolify + Postgres)

Without these exclusions, `mdatp` scans every container layer write — that's
hundreds of MB per `docker pull` and constant churn on Postgres WAL. Symptoms:
sustained 20–40% CPU on `mdatp`, builds timing out in Coolify.

Run on **all three servers** (paths are identical):

```bash
# Docker storage
mdatp exclusion folder add --path /var/lib/docker/overlay2
mdatp exclusion folder add --path /var/lib/docker/volumes
mdatp exclusion folder add --path /var/lib/docker/containers
mdatp exclusion folder add --path /var/lib/docker/buildkit

# Coolify
mdatp exclusion folder add --path /data/coolify
mdatp exclusion folder add --path /var/lib/coolify

# Verify
mdatp exclusion folder list
```

Additionally on **NEXUS only** (has bind-mounted Postgres + Qdrant data):

```bash
mdatp exclusion folder add --path /var/lib/postgresql
mdatp exclusion folder add --path /var/lib/docker/volumes/nexus_qdrant_data
```

## 4. Real-time protection policy (per server)

Defaults to ON after install. Atlas needs it OFF:

```bash
# On Atlas (78.47.89.127) ONLY:
ssh root@78.47.89.127 "mdatp config real-time-protection --value disabled"
ssh root@78.47.89.127 "mdatp health --field real_time_protection_enabled"
# expected: false
```

NEXUS and Compass keep the default (`enabled`). To re-enable on Atlas later
(e.g. after another resource rescale):

```bash
mdatp config real-time-protection --value enabled
```

Scheduled scans on Atlas (no real-time): quick scan daily, full scan weekly.
Configure in M365 Defender portal → Endpoints → Configuration management →
Endpoint security policies → Antivirus → assign policy to Atlas device group.

## 5. Performance baseline (after 24 hours)

After 24 hours of normal traffic, sanity-check `mdatp` resource usage on every
host:

```bash
ssh root@91.99.199.112 "mdatp health --details && top -bn1 -p \$(pgrep -d, mdatp)"
```

Expected ceilings:

| Metric | NEXUS / Compass (real-time ON) | Atlas (real-time OFF) |
|---|---|---|
| `mdatp` CPU sustained | < 5% | < 1% |
| `mdatp` memory RSS | < 200 MB | < 100 MB |
| `mdatp` CPU during scan | < 30% spike | < 30% spike |

If `mdatp` exceeds these (>20% sustained CPU or >500 MB memory), the most
common cause is a missing exclusion — re-run `mdatp exclusion folder list` and
compare with [section 3](#3-configure-exclusions-docker--coolify--postgres).
Last resort: tweak scan policies in M365 Defender portal.

## 6. Monitoring in M365 Defender portal

1. **Devices**: all three servers should appear within 10–20 minutes of
   onboarding, status `Active`. Tag each device:

   | Server | Tags |
   |---|---|
   | NEXUS | `production`, `nexus`, `realtime-on` |
   | Compass | `production`, `compass`, `realtime-on` |
   | Atlas | `production`, `atlas`, `realtime-off` |

2. **Alerts**: target `0` high-severity, `0` critical-medium alerts. False
   positives on Docker overlay layers are the expected initial noise — add
   the offending path to exclusions and dismiss the alert.

3. **Email notifications**: Settings → Endpoints → Email notifications →
   Add rule:

   - **Severity**: High, Medium
   - **Device groups**: all
   - **Recipients**: `artek9321@gmail.com`

4. **Auto-investigation**: Settings → Endpoints → Advanced features → enable
   `Automated investigation` and `Auto resolve alerts (Standard)`. This lets
   Defender quarantine known-bad files without manual approval.

## 7. Verify Coolify deploys still work

After install on each server, trigger a non-invasive deploy to confirm the
Defender daemon doesn't interfere with Coolify's build pipeline:

```bash
# Push an empty doc commit on a feature branch, or trigger manually:
TOKEN="<COOLIFY_TOKEN from gh secret list --repo artur-t-96/Nexus>"
APP_UUID="ocgkwcbovpve9wvf9smxl0kx"  # NEXUS
curl -X GET -H "Authorization: Bearer $TOKEN" \
  "https://coolify-nexus.dynaminds.pl/api/v1/deploy?uuid=$APP_UUID&force=true"

# Watch deploy logs in Coolify panel; expect green within 90s smoke window.
# Repeat for Compass (w136dv828ofipvjfnxrqi643) + Atlas (fdga7gk59n10vebipz1ua17h).
```

If the deploy hangs at the build stage or Coolify reports OOM, the most
likely cause is `mdatp` scanning `/var/lib/docker/buildkit` during the build —
verify it's in the exclusion list.

## Troubleshooting

### `mdatp health` returns `healthy: false`

Check the connection side first:

```bash
mdatp connectivity test
# tests Microsoft cloud endpoints; all should be "OK"
```

If any endpoint fails, the host firewall (UFW or Hetzner Cloud Firewall) is
blocking outbound HTTPS to:

- `*.endpoint.security.microsoft.com`
- `*.events.data.microsoft.com`
- `*.cdn.x.cp.wd.microsoft.com`

Allow outbound 443 to these CNAMEs. The full endpoint list and IP ranges live
[here](https://learn.microsoft.com/en-us/microsoft-365/security/defender-endpoint/linux-support-connectivity).

### Device doesn't appear in Defender portal

After install, propagation can take up to 30 minutes. Force a heartbeat:

```bash
systemctl restart mdatp
mdatp health --field org_id
# expected: GUID of your tenant, not "00000000-..."
```

If `org_id` is all zeros, the onboarding script didn't apply — re-run step
2.4 with the original ZIP package.

### `mdatp` daemon won't start after reboot

```bash
systemctl status mdatp
journalctl -u mdatp --since "1 hour ago" | tail -50
```

Most common cause: kernel update mismatched with `mdatp` AuditD hooks. Fix:

```bash
apt-get install --reinstall mdatp
systemctl restart mdatp
```

### Logs location

- Daemon logs: `/var/log/microsoft/mdatp/microsoft_defender_core.log`
- Onboarding logs: `/var/log/microsoft/mdatp/install.log`
- AV scan logs: `/var/log/microsoft/mdatp/microsoft_defender_avscan.log`

## Offboarding (if a server is decommissioned)

1. M365 Defender portal → Settings → Endpoints → Offboarding → Linux Server →
   download offboarding script (valid 30 days).
2. SSH to the doomed server → upload + run script.
3. `apt-get remove --purge mdatp && rm -rf /var/log/microsoft /etc/opt/microsoft/mdatp`.

License returns to the pool within 24 hours and can be assigned to a
replacement server via the same onboarding flow.

## Renewal reminder

License expires **2027-02-10**. Add a calendar reminder 60 days out
(2026-12-12) to renew via Partner center. If not renewed, devices keep
reporting but the M365 portal will display them as `Unlicensed` and stop
applying policies.

## Reference

- [Install Defender for Endpoint on Linux manually](https://learn.microsoft.com/en-us/microsoft-365/security/defender-endpoint/linux-install-manually)
- [Connectivity troubleshooting](https://learn.microsoft.com/en-us/microsoft-365/security/defender-endpoint/linux-support-connectivity)
- [Exclusions configuration](https://learn.microsoft.com/en-us/microsoft-365/security/defender-endpoint/linux-exclusions)
- [Resource consumption tuning](https://learn.microsoft.com/en-us/microsoft-365/security/defender-endpoint/linux-support-perf)

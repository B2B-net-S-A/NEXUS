# Gitleaks full-history inventory — 2026-07-13

Scanner: Gitleaks 8.21.2, 904 commits, `.gitleaks.toml` from the P0 patch.
This report intentionally contains only commit, path, rule, and fingerprint. It
contains no secret values.

Only the retired bootstrap-password finding is exact-fingerprint baselined in
`.gitleaksignore`. The remaining 28 findings, including five committed demo-user
passwords, are **not** baselined and keep the incident at P0 until they are
classified and every corresponding credential/account is confirmed retired.

| Commit | Path | Rule | Fingerprint |
|---|---|---|---|
| `777e1b8b463f40add996f95f5b0da4cc24da4e55` | `backend/scripts/migrate_dynareporter.py` | `hardcoded-db-password` | `777e1b8b463f40add996f95f5b0da4cc24da4e55:backend/scripts/migrate_dynareporter.py:hardcoded-db-password:32` |
| `4714a91b55bb03c69b649ad547656fe05416d904` | `backend/scripts/ensure_claude_admin.py` | `hardcoded-bootstrap-password` | `4714a91b55bb03c69b649ad547656fe05416d904:backend/scripts/ensure_claude_admin.py:hardcoded-bootstrap-password:36` |
| `ab6449cc36c52820404ddc3edf785eecfb28c2c1` | `docs/phase12-polish-2026-04-18.md` | `generic-api-key` | `ab6449cc36c52820404ddc3edf785eecfb28c2c1:docs/phase12-polish-2026-04-18.md:generic-api-key:58` |
| `bf5cb10f830ed89239de6bbfde42cf59ab8855be` | `.local-state/coolify.env.backup` | `generic-api-key` | `bf5cb10f830ed89239de6bbfde42cf59ab8855be:.local-state/coolify.env.backup:generic-api-key:9` |
| `bf5cb10f830ed89239de6bbfde42cf59ab8855be` | `.local-state/coolify.env.backup` | `generic-api-key` | `bf5cb10f830ed89239de6bbfde42cf59ab8855be:.local-state/coolify.env.backup:generic-api-key:10` |
| `bf5cb10f830ed89239de6bbfde42cf59ab8855be` | `.local-state/coolify_github_deploy_key.txt` | `private-key` | `bf5cb10f830ed89239de6bbfde42cf59ab8855be:.local-state/coolify_github_deploy_key.txt:private-key:18` |
| `bf5cb10f830ed89239de6bbfde42cf59ab8855be` | `.local-state/coolify_setup_info.txt` | `generic-api-key` | `bf5cb10f830ed89239de6bbfde42cf59ab8855be:.local-state/coolify_setup_info.txt:generic-api-key:16` |
| `bf5cb10f830ed89239de6bbfde42cf59ab8855be` | `.local-state/prod_secrets.env` | `generic-api-key` | `bf5cb10f830ed89239de6bbfde42cf59ab8855be:.local-state/prod_secrets.env:generic-api-key:3` |
| `bf5cb10f830ed89239de6bbfde42cf59ab8855be` | `.local-state/prod_secrets.env` | `generic-api-key` | `bf5cb10f830ed89239de6bbfde42cf59ab8855be:.local-state/prod_secrets.env:generic-api-key:4` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `.env` | `voyage-api-key` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:.env:voyage-api-key:12` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `.env` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:.env:hardcoded-db-password:6` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `.env` | `fireflies-api-key` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:.env:fireflies-api-key:27` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `.env.example` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:.env.example:hardcoded-db-password:13` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/app/core/config.py` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/app/core/config.py:hardcoded-db-password:14` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/entrypoint.sh` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/entrypoint.sh:hardcoded-db-password:14` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/app/services/infrareporter.py` | `generic-api-key` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/app/services/infrareporter.py:generic-api-key:16` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/embed_all.py` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/embed_all.py:hardcoded-db-password:28` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed_v5.py` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed_v5.py:hardcoded-db-password:25` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed_v4.py` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed_v4.py:hardcoded-db-password:22` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `docker-compose.yml` | `voyage-api-key` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:docker-compose.yml:voyage-api-key:42` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `docker-compose.yml` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:docker-compose.yml:hardcoded-db-password:34` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `docker-compose.yml` | `fireflies-api-key` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:docker-compose.yml:fireflies-api-key:41` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed_v6_pipeline.py` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed_v6_pipeline.py:hardcoded-db-password:26` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed.py` | `demo-seed-literal-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed.py:demo-seed-literal-password:79` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed.py` | `demo-seed-literal-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed.py:demo-seed-literal-password:86` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed.py` | `demo-seed-literal-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed.py:demo-seed-literal-password:93` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed.py` | `demo-seed-literal-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed.py:demo-seed-literal-password:100` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed.py` | `demo-seed-literal-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed.py:demo-seed-literal-password:107` |
| `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa` | `backend/seed.py` | `hardcoded-db-password` | `38bd32fa7fc9378f8d4968cdb364e3e0d5bf03fa:backend/seed.py:hardcoded-db-password:40` |

No history was rewritten and no credential was rotated by this repository patch.

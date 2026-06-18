# CV preview event-loop blocking — completion report

**Data:** 2026-06-18
**PR:** [#541](https://github.com/artur-t-96/Nexus/pull/541) (merge `a44db8e`)
**Zgłoszenie:** „Kliknąłem podgląd CV na kandydacie i czekałem minutę aż się otworzy. Ma być: podgląd CV otwiera się maksymalnie po kilku sekundach."

## Root cause

Endpoint `GET /api/candidates/{id}/documents/{doc}/content` (zakładka Profil → „Otwórz", zakładka Pliki → „Podgląd") wołał **synchroniczny boto3** `download_cv()` (`get_object().read()`) **wprost w `async` handlerze, bez `run_in_threadpool`/`asyncio.to_thread`**. Na jedno-workerowym uvicornie (`exec uvicorn app.main:app`, brak `--workers`) blokowało to event loop na cały czas pobierania pliku z Hetzner Object Storage — stąd zarówno wolny sam podgląd, jak i kontencja z pozostałymi requestami/background taskami.

### Dowody (prod, przed fixem)

| Pomiar | Wartość |
|---|---|
| Sentry transakcja `download_candidate_document` (14 dni) | avg **7.6s**, p50 7.6s, p95 **14.9s** |
| Live `/content` doc 76128 (Jakub Bukowski, 398 KB) | total **8–17s**, TTFB **6.5s**, sporadyczny 500 |
| Test współbieżności: `/api/health` podczas pobierania CV | **8.3s** + **503** (loop zagłodzony; baseline ~2.2s) |
| DB SELECT doca (Sentry span) | ~5ms p50, 8ms p95 — **nie** wąskie gardło |

## Fix

Offload synchronicznego blocking I/O do worker-threada — wzorzec już używany w `cv_source.py:68` (`run_in_threadpool`) i w `candidates.py` (`asyncio.to_thread`, linie ~3558/3765). Semantycznie transparentne (ta sama wartość zwracana, te same wyjątki propagują).

| Plik | Funkcja / endpoint | Blokujące wywołanie | Wrap |
|---|---|---|---|
| `backend/app/api/candidates.py:3070` | `download_candidate_document` (`/content`) | `download_cv` (boto3 get) | `asyncio.to_thread` ← **zgłoszony bug** |
| `backend/app/api/candidates.py:3926` | `bulk_cv_download` | `_download_cv` w pętli (do 200 CV) | `asyncio.to_thread` |
| `backend/app/api/cv_match_preview.py:216` | `cv_upload_preview` | `extract_text` (PDF/OCR, do ~50s) | `run_in_threadpool` |
| `backend/app/services/cv_parser.py:278` | `_parse_with_claude` | synchroniczny Anthropic SDK | `run_in_threadpool` |
| `backend/app/api/jobs.py:1601` | `set_champion_briefing` | `upload_briefing_audio` (boto3 put) | `run_in_threadpool` |
| `backend/app/api/jobs.py:1697` | `clear_champion_briefing` | `delete_cv` (boto3 delete) | `run_in_threadpool` |

## Weryfikacja (prod, po deployu `a44db8e`)

| Pomiar | Przed | Po |
|---|---|---|
| `/content` doc 76128 (6 runów) | 8–17s / TTFB 6.5s | **1.2–1.7s / TTFB 0.2s** ✅ |
| `/api/health` podczas pobierania CV | 8.3s + 503 | **0.5s, 200** ✅ (loop wolny) |
| `/api/health` baseline | ~2.2s | **~0.4s** ✅ (kontencja zelżała) |
| `bulk-cv-download` (3 CV, 1.6 MB) | — | **1.8s** ✅ |
| Chrome MCP: klik „Otwórz" na kandydacie 179260 | stuck „Ładowanie…" | **modal + PDF (2 str.) w ~2s** ✅ |

CI: backend (ruff+pytest), frontend (tsc+build), gitleaks, trivy — green. Deploy smoke-test (version match) — pass.

## Audyt — pozostałe blokery event-loopa (FOLLOW-UP, poza zakresem tego PR)

Workflow (49 agentów, adversarial verify) wykrył **~20 request-path + 9 background** blokerów event-loopa tej samej klasy. Naprawiona tu została **ścieżka CV/dokumentów/media**. Do osobnego PR (priorytet: HIGH severity najpierw):

**Request-path (HIGH):**
- `services/champion_draft_service.py:112` — `_call_claude_json` sync Anthropic (współdzielony przez generate_from_jd / enrich_from_meeting / generate_from_historical_jobs / CloudTalk webhook `enrich_from_call`).

**Request-path (MEDIUM/LOW):**
- `api/b2b_contract_generator.py` ×5 — `render_contract_docx` / `render_from_context` (DOCX render) + Jinja `render` (linie 282, 340, 460, 527, 607).
- `api/ai_writer.py:251` — sync Anthropic (`/ai/generate-job`).
- `api/dynareporter_mindy.py:167,212` — sync Anthropic (`/commentary`, `/chat`).
- `services/stage_notification_emitter.py:125` + `services/mention_dispatch.py:206` — `smtplib.SMTP` (blocking SMTP w pętli po odbiorcach).
- `services/signing/pades.py:141` — pyHanko PDF parse.
- `api/import_export.py:210` — CSV build nad całą tabelą kandydatów.

**Background-task (HIGH — blokują loop okresowo, gdy odpalą):**
- `services/traffit/importer.py:1373,1584` — `upload_cv` (boto3 put) w pętli importu.
- `services/talent_radar_importer.py:276` — `upload_cv` (boto3 put) per wiersz.

**Background-task (MEDIUM/LOW):**
- `tasks/chat_email_fallback.py:58` — SMTP.
- `tasks/autenti_expiry_sweeper.py:173` — sync file write.
- `services/m365/attachment_handler.py:163,165` — file write + sha256.
- `services/m365/sync.py:366,368` — bleach `sanitize_html`/`html_to_text` (CPU).

**Wzorzec poprawki dla wszystkich:** wrap synchronicznego wywołania w `await run_in_threadpool(fn, ...)` (z `fastapi.concurrency`) lub `await asyncio.to_thread(fn, ...)`. Dla sync Anthropic alternatywnie migracja na `AsyncAnthropic`. `generate_presigned_url` jest LOKALNE (signature, brak sieci) — **nie** wymaga wrapa (odrzucone w audycie).

**Pełny audyt:** workflow run `wf_522e5044-035`.

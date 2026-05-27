/**
 * E2E flow stubs — TODO list dla pozostałych 27 critical flows.
 *
 * Każdy stub = `test.fixme()` ze szczegółowym opisem co testować + jaki
 * acceptance criteria. Spawn task chip "Implement E2E flow stubs" przejmie
 * implementację per-stub w follow-up sesji (~3-5 specs/sesja).
 *
 * Priorytet (per QA session 2026-05-27 manual coverage gap analysis):
 * P1 — core feature (block deploy gdy fail)
 * P2 — high impact UX
 * P3 — nice-to-have
 */
import { test } from "@playwright/test";

test.describe("E2E flow stubs — TODO (27 flows)", () => {
  // ── Candidate operations ────────────────────────────────────────────────
  test.fixme("P1 import CSV → 5 candidates z prefix → counts match", () => {
    // helpers.sampleCandidatesCsv() → POST /api/candidates/import-csv → verify
    // tracker.cleanup po (5 candidates).
  });

  test.fixme("P1 import z CV (PDF parse) → AI extract → candidate created", () => {
    // Upload sample PDF z CV → POST /api/candidates/from-cv → verify ai_summary
    // populated + experience array parsed.
  });

  test.fixme("P1 bulk CV download (ZIP) → 5 candidates selected", () => {
    // GET /api/candidates/bulk-cv-download?ids=1,2,3,4,5 → verify zip mime
    // type + content disposition + contains 5 PDF files.
  });

  test.fixme("P2 search candidate top searchbar by name/email/phone", () => {
    // Type in top searchbar → verify dropdown results match + click → opens drawer.
  });

  test.fixme("P2 candidate wrzuć na targ z TTL", () => {
    // POST /api/marketplace/listings z candidate_id, expires_at → verify
    // appears w /marketplace?tab=manual + auto-removed po expiry.
  });

  // ── Job operations ──────────────────────────────────────────────────────
  test.fixme("P1 POST /api/jobs → auto-assign TAC + DL z primary clients TAC", () => {
    // Per `[[project_auto_assign_owners]]`: stwórz job dla Nordea → verify
    // response.tac_id = primary TAC Nordea, response.delivery_lead_id = head DL.
  });

  test.fixme("P1 edit job → PATCH fields → verify w UI", () => {
    // PATCH /api/jobs/{id} z {title, salary_min, salary_max} → GET → verify.
  });

  test.fixme("P1 AddCandidatesQuickModal — add 3 candidates do job", () => {
    // Z /jobs/{id} kliknij Add candidates → search → bulk select → POST →
    // verify 3 candidate_stages utworzone.
  });

  test.fixme("P1 close job z reason → verify status='closed' + close_reason set", () => {
    // POST /api/jobs/{id}/close z {reason: 'filled_by_us', notes} → verify.
  });

  test.fixme("P2 generate AI ogłoszenie z job description", () => {
    // POST /api/jobs/{id}/ai-job-posting → verify OpenAI/Claude response
    // contains job title + skills + nice formatting.
  });

  // ── Interview + calendar ────────────────────────────────────────────────
  test.fixme("P1 schedule interview → verify w kalendarzu + actionable card", () => {
    // POST /api/calendar/events z type=interview → verify event w GET /api/calendar/events
    // + jeśli M365 enabled, verify Outlook actionable message sent.
  });

  test.fixme("P2 post-interview feedback form", () => {
    // POST /api/interview-feedback z scoring 1-5 + comments → verify
    // candidate_stage rating updated.
  });

  // ── Communication (M365 / Tiptap) ───────────────────────────────────────
  test.fixme("P1 send email do kandydata via M365", () => {
    // POST /api/emails z to, subject, body → verify Email row created +
    // jeśli M365 connected, real send via Graph API.
  });

  test.fixme("P2 upload plik PDF do kandydata", () => {
    // POST /api/candidates/{id}/files z multipart PDF → verify file row + S3 upload.
  });

  // ── Contracts (Umowa) — P0 biznes ───────────────────────────────────────
  test.fixme("P0 create contract draft → Tiptap edit → finalize", () => {
    // POST /api/contracts z draft state → PATCH content_html → POST /finalize
    // → verify status flow: draft → finalize_pending → active.
  });

  test.fixme("P0 render contract PDF preview", () => {
    // GET /api/contracts/{id}/render-pdf → verify PDF mime + > 1KB size.
  });

  test.fixme("P1 send contract via Autenti (gdy AUTENTI_ENABLED=true)", () => {
    // POST /api/autenti/contracts/{id}/send → verify Autenti response +
    // signature row utworzony.
  });

  // ── Talent management ───────────────────────────────────────────────────
  test.fixme("P2 add candidate do talent pool", () => {
    // POST /api/talent-pools/{id}/members z candidate_id → verify.
  });

  test.fixme("P2 marketplace match — AI matchuje pool members do open jobs", () => {
    // POST /api/marketplace/match z job_id → verify top 10 candidates ranked.
  });

  // ── Client management ───────────────────────────────────────────────────
  test.fixme("P1 create client → fill NIP/REGON/branża → verify", () => {
    // POST /api/clients z data → verify response + appears w GET /api/clients.
  });

  test.fixme("P1 add contact do klienta (Decydent flag)", () => {
    // POST /api/clients/{id}/contacts z is_decision_maker=true → verify.
  });

  test.fixme("P1 create MSA (umowa ramowa) z Autenti send", () => {
    // POST /api/clients/{id}/framework-contracts → verify MSA + Autenti dispatch.
  });

  test.fixme("P2 create SOW order z MSA reference", () => {
    // POST /api/orders z msa_id, value, deadline → verify.
  });

  // ── Settings / integrations ─────────────────────────────────────────────
  test.fixme("P1 OAuth M365 connection flow", () => {
    // GET /api/microsoft365/oauth/authorize → mock callback → POST /callback
    // z code → verify M365Connection row created + Graph token encrypted.
  });

  test.fixme("P2 configure Teams notifications channel", () => {
    // POST /api/teams-channels z channel_id, webhook_url → verify.
  });

  // ── DL Hub workflows ────────────────────────────────────────────────────
  test.fixme("P1 verify pending candidate (Accept/Reject)", () => {
    // Setup: create candidate at stage=verified z verification_status=pending.
    // POST /api/pipeline/pending-verifications/{id}/approve → verify status=active.
  });

  test.fixme("P2 DL→client assignment przez /api/clients/{id}/team", () => {
    // POST z dl_user_id, is_head=true → verify DL appears w Zespół tab.
  });
});

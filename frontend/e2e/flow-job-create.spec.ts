/**
 * E2E flow: job create + bulk add candidates.
 *
 * Pokrywa 2 stubs z `flow-stubs-todo.spec.ts`:
 * - P1 POST /api/jobs → auto-assign TAC + DL z primary clients TAC
 *   (per `[[project_auto_assign_owners]]`)
 * - P1 AddCandidatesQuickModal — add N candidates do job
 *
 * Klucze gotcha (per backend research 2026-05-28):
 * - Canonical bulk-add endpoint: `/api/jobs/{job_id}/proposals/bulk`
 *   (NIE `/api/jobs/{id}/candidates` — to wzorzec dla DELETE w innych miejscach
 *   i nie istnieje jako POST). `/api/candidate-stages` służy do *przesuwania*
 *   między stages, nie do initial bulk-add.
 * - Auto-assign czerpie z `client_tac_assignments.is_primary=TRUE` +
 *   `delivery_lead_client_assignments.is_head=TRUE` AND user.is_active=TRUE.
 *   Klient bez assignments → response.tac_id/delivery_lead_id = null.
 * - jobs.client_id NOT NULL od migracji 0120 (2026-05-27).
 * - Job status default: draft.
 *
 * Cleanup: DELETE job + 3 candidates.
 */
import { test, expect, APIRequestContext } from "@playwright/test";
import { EntityTracker, uniqueName } from "./helpers/test-entities";

const tracker = new EntityTracker();

test.afterEach(async ({ request }) => {
  const { deleted, failed } = await tracker.cleanup(request);
  if (failed > 0) {
    console.warn(`[cleanup] ${deleted} deleted, ${failed} FAILED — possible orphan`);
  }
});

interface AssignedClient {
  clientId: number;
  primaryTacUserId: number;
  headDlUserId: number;
}

async function findClientWithPrimaryTacAndHeadDL(
  request: APIRequestContext,
): Promise<AssignedClient | null> {
  // Iteruj listę klientów (do 30 prób — wystarczająco, większy zakres = duża
  // strata czasu; per project memory wiele klientów ma TAC+DL skonfigurowanych).
  const list = await request.get("/api/clients?limit=30");
  if (!list.ok()) return null;
  const data = await list.json();
  const clients = Array.isArray(data) ? data : (data.items ?? data.results ?? []);

  for (const c of clients) {
    const team = await request.get(`/api/clients/${c.id}/team`);
    if (!team.ok()) continue;
    const t = await team.json();
    const primaryTac = (t.tacs ?? []).find((x: any) => x.is_primary);
    const headDl = (t.delivery_leads ?? []).find((x: any) => x.is_head);
    if (primaryTac && headDl) {
      return {
        clientId: c.id,
        primaryTacUserId: primaryTac.user_id,
        headDlUserId: headDl.user_id,
      };
    }
  }
  return null;
}

test.describe("Flow: job create + bulk add candidates", () => {
  test("POST /api/jobs without tac_id/dl_id → auto-fill z primary TAC + head DL", async ({
    request,
  }) => {
    const assigned = await findClientWithPrimaryTacAndHeadDL(request);
    test.skip(
      assigned === null,
      "no client with primary TAC + head DL — auto-assign test impossible",
    );

    const create = await request.post("/api/jobs", {
      data: {
        title: uniqueName("job"),
        client_id: assigned!.clientId,
        description: "QA E2E test job — auto-assign verification.",
        status: "draft",
      },
    });
    expect(create.status(), "job create must succeed").toBe(201);
    const job = await create.json();
    tracker.track("/api/jobs", job.id);

    expect(
      job.tac_id,
      `tac_id should auto-fill from primary TAC of client ${assigned!.clientId}`,
    ).toBe(assigned!.primaryTacUserId);
    expect(
      job.delivery_lead_id,
      `delivery_lead_id should auto-fill from head DL of client ${assigned!.clientId}`,
    ).toBe(assigned!.headDlUserId);
  });

  test("POST /api/jobs/{job_id}/proposals/bulk z 3 candidates → total_added=3", async ({
    request,
  }) => {
    // 1. Stwórz 3 test candidates
    const candidateIds: number[] = [];
    for (let i = 0; i < 3; i++) {
      const candCreate = await request.post("/api/candidates", {
        data: {
          name: uniqueName("bulk").split(" ")[0],
          lastname: `Bulk-${i}`,
          email: `qa-e2e-bulk-${Date.now()}-${i}@test.local`,
          source: "manual",
          status: "active",
          availability_status: "unknown",
        },
      });
      expect([200, 201]).toContain(candCreate.status());
      const c = await candCreate.json();
      candidateIds.push(c.id);
      tracker.track("/api/candidates", c.id);
    }
    expect(candidateIds.length).toBe(3);

    // 2. Stwórz testowy job (jakikolwiek istniejący client_id — auto-assign
    // jest osobny test, tutaj nie ma znaczenia).
    const clients = await request.get("/api/clients?limit=1");
    expect(clients.ok()).toBe(true);
    const cd = await clients.json();
    const clientList = Array.isArray(cd) ? cd : (cd.items ?? cd.results ?? []);
    test.skip(clientList.length === 0, "no clients in DB");
    const clientId = clientList[0].id;

    const jobCreate = await request.post("/api/jobs", {
      data: {
        title: uniqueName("job-bulk"),
        client_id: clientId,
        status: "draft",
      },
    });
    expect(jobCreate.status()).toBe(201);
    const job = await jobCreate.json();
    tracker.track("/api/jobs", job.id);

    // 3. POST bulk proposals — canonical AddCandidatesQuickModal endpoint.
    const bulk = await request.post(`/api/jobs/${job.id}/proposals/bulk`, {
      data: { candidate_ids: candidateIds },
    });
    expect(bulk.status(), "bulk add proposals must return 200").toBe(200);
    const body = await bulk.json();
    expect(body).toHaveProperty("added");
    expect(body).toHaveProperty("skipped");
    expect(body).toHaveProperty("total_added");
    expect(body).toHaveProperty("total_skipped");
    // Nowe kandydaty + świeży job → wszyscy 3 powinni przejść (zero skipped).
    expect(body.total_added).toBe(3);
    expect(body.total_skipped).toBe(0);
    expect(body.added.length).toBe(3);

    // 4. Idempotency — drugi POST tych samych ID powinien wszystkich zskipować
    // jako already_in_job.
    const bulk2 = await request.post(`/api/jobs/${job.id}/proposals/bulk`, {
      data: { candidate_ids: candidateIds },
    });
    expect(bulk2.status()).toBe(200);
    const body2 = await bulk2.json();
    expect(body2.total_added).toBe(0);
    expect(body2.total_skipped).toBe(3);
    expect(
      body2.skipped.every((s: any) => s.reason === "already_in_job"),
      "second POST must mark all as already_in_job",
    ).toBe(true);
  });
});

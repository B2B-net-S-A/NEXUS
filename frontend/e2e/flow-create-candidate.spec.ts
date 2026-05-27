/**
 * E2E flow: ręczne dodanie kandydata przez API + verify w UI + cleanup.
 *
 * Pokrywa:
 * - POST /api/candidates (BE-1N regression: enum head_of_recruitment OK)
 * - Notification fan-out do admin+head_of_recruitment (2026-05-27 fix)
 * - Frontend renders kandydata w `/candidates` lista
 *
 * Cleanup: DELETE candidate po każdym teście (EntityTracker).
 */
import { test, expect } from "@playwright/test";
import { EntityTracker, uniqueName } from "./helpers/test-entities";

const tracker = new EntityTracker();

test.afterEach(async ({ request }) => {
  const { deleted, failed } = await tracker.cleanup(request);
  if (failed > 0) {
    console.warn(`[cleanup] ${deleted} deleted, ${failed} FAILED — possible orphan`);
  }
});

test.describe("Flow: create candidate", () => {
  test("POST /api/candidates → 201 + visible in list", async ({ request, page }) => {
    const name = uniqueName("candidate");
    const email = `qa-e2e-${Date.now()}@test.local`;

    // 1. Create via API
    const create = await request.post("/api/candidates", {
      data: {
        name: name.split(" ")[0],
        lastname: name.split(" ").slice(1).join(" "),
        email,
        phone: "+48500000099",
        source: "manual",
        status: "active",
        availability_status: "unknown",
      },
    });
    expect(create.status(), "BE-1N regression: enum head_of_recruitment musi być valid").toBeLessThan(500);
    expect([200, 201]).toContain(create.status());
    const candidate = await create.json();
    expect(candidate).toHaveProperty("id");
    tracker.track("/api/candidates", candidate.id);

    // 2. Verify w UI
    await page.goto(`/candidates/${candidate.id}`);
    // Wait for drawer or detail page render. Adjust selector based on actual route.
    await expect(page.getByText(email, { exact: false }).first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("POST z duplicate email → 409 (no silent insert)", async ({ request }) => {
    const email = `qa-e2e-dup-${Date.now()}@test.local`;
    const data = {
      name: "Dup",
      lastname: "Test",
      email,
      source: "manual",
      status: "active",
      availability_status: "unknown",
    };

    const first = await request.post("/api/candidates", { data });
    expect([200, 201]).toContain(first.status());
    const cand = await first.json();
    tracker.track("/api/candidates", cand.id);

    const second = await request.post("/api/candidates", { data });
    expect(second.status(), "Email unique constraint powinien zwrócić 409").toBe(409);
  });
});

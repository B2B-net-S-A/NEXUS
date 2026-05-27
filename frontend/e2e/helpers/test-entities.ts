/**
 * Test entity helpers — prefixed names + cleanup utilities.
 *
 * Wszystkie E2E flows które tworzą real data w prod (kandydaci, joby, notatki,
 * kontrakty, etc.) MUSZĄ używać tych helperów aby:
 * 1. Stworzona entities miały prefix `[QA-E2E-{timestamp}]` (łatwe wykrycie + cleanup)
 * 2. Auto-cleanup w `afterEach` / `afterAll` przez DELETE API call
 * 3. Jeśli cleanup zawiedzie, nightly cron `e2e-cleanup` (TODO) usuwa orphan
 *    entities starsze niż 24h
 *
 * Bez tych helperów: każda sesja CI zostawia śmieci w prod DB (jak
 * `[E2E-PendingVerif] DELETE ME` z 2026-05-27 sesji QA — bug #21).
 */
import { APIRequestContext } from "@playwright/test";

export const E2E_PREFIX = `[QA-E2E-${new Date().toISOString().slice(0, 10)}]`;

/** Unique entity name dla danej sesji — np. `[QA-E2E-2026-05-27] candidate-a3f7` */
export function uniqueName(category: string): string {
  const random = Math.random().toString(36).slice(2, 6);
  return `${E2E_PREFIX} ${category}-${random}`;
}

/** Detect czy nazwa zwiera nasz prefix — używane w cleanup */
export function isE2ETestEntity(name: string | null | undefined): boolean {
  if (!name) return false;
  return name.startsWith("[QA-E2E-");
}

/**
 * Tracker dla created entities w trakcie testu. Wywołaj `track()` po każdym
 * `POST` → w `afterEach` automatycznie `cleanup()` zrobi DELETE.
 */
export class EntityTracker {
  private created: Array<{ endpoint: string; id: number }> = [];

  track(endpoint: string, id: number): void {
    this.created.push({ endpoint, id });
  }

  async cleanup(request: APIRequestContext): Promise<{ deleted: number; failed: number }> {
    let deleted = 0;
    let failed = 0;
    // Reverse order — usuń child entities przed parent (np. candidate przed job)
    for (const { endpoint, id } of this.created.reverse()) {
      try {
        const r = await request.delete(`${endpoint}/${id}`);
        if (r.ok() || r.status() === 404) deleted++;
        else failed++;
      } catch {
        failed++;
      }
    }
    this.created = [];
    return { deleted, failed };
  }

  get count(): number {
    return this.created.length;
  }
}

/**
 * Sample CSV content (5 candidates) for import tests. Wszyscy z prefix
 * w name żeby cleanup wykrył je w bazie.
 */
export function sampleCandidatesCsv(): string {
  const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  const rows = [
    ["name", "lastname", "email", "phone"],
    [`${E2E_PREFIX} CSV-${ts}-1`, "Test", `qa-e2e-${ts}-1@test.local`, "+48500000001"],
    [`${E2E_PREFIX} CSV-${ts}-2`, "Test", `qa-e2e-${ts}-2@test.local`, "+48500000002"],
    [`${E2E_PREFIX} CSV-${ts}-3`, "Test", `qa-e2e-${ts}-3@test.local`, "+48500000003"],
    [`${E2E_PREFIX} CSV-${ts}-4`, "Test", `qa-e2e-${ts}-4@test.local`, "+48500000004"],
    [`${E2E_PREFIX} CSV-${ts}-5`, "Test", `qa-e2e-${ts}-5@test.local`, "+48500000005"],
  ];
  return rows.map((r) => r.join(",")).join("\n");
}

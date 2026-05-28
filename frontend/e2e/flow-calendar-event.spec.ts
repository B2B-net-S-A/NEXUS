/**
 * E2E flow: schedule interview event w kalendarzu.
 *
 * Pokrywa 1 stub z `flow-stubs-todo.spec.ts`:
 * - P1 schedule interview → verify w kalendarzu + actionable card
 *
 * Klucze gotcha (per backend research 2026-05-28):
 * - Path: `/api/calendar/events` (router prefix `/api`).
 * - Required body: `title` + `start_time`. Wszystko inne optional.
 * - `event_type` enum: interview | screening | prep_call | meeting | deadline.
 * - Response: 201 + enriched `candidate_name` / `job_title` / `client_name` joiny.
 * - M365 Actionable Messages (Outlook button) is gated separately by
 *   `M365_INTEGRATION_ENABLED` + per-user OAuth — tu testujemy local DB
 *   round-trip, NIE faktyczny outbound do Outlook (to wymaga prod M365 setup).
 *
 * Cleanup: DELETE event + candidate. Brak orphan attendee rows do czyszczenia.
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

test.describe("Flow: schedule interview event", () => {
  test("POST /api/calendar/events z event_type=interview → enriched response + visible w GET", async ({
    request,
  }) => {
    // 1. Stwórz test candidate jako attachment do eventu
    const candCreate = await request.post("/api/candidates", {
      data: {
        name: uniqueName("interview").split(" ")[0],
        lastname: "Calendar",
        email: `qa-e2e-cal-${Date.now()}@test.local`,
        source: "manual",
        status: "active",
        availability_status: "unknown",
      },
    });
    expect([200, 201]).toContain(candCreate.status());
    const candidate = await candCreate.json();
    tracker.track("/api/candidates", candidate.id);

    // 2. Schedule interview na +1 godzinę (przyszłość — dla testu RRULE
    // / reminder nie ma znaczenia bo nie czekamy na reminder fire).
    const startTime = new Date(Date.now() + 60 * 60 * 1000).toISOString();
    const endTime = new Date(Date.now() + 90 * 60 * 1000).toISOString();

    const title = uniqueName("interview-slot");
    const create = await request.post("/api/calendar/events", {
      data: {
        title,
        description: "QA E2E test interview slot.",
        event_type: "interview",
        start_time: startTime,
        end_time: endTime,
        candidate_id: candidate.id,
        reminder_minutes: 15,
      },
    });
    expect(create.status(), "interview event create must return 201").toBe(201);
    const event = await create.json();
    tracker.track("/api/calendar/events", event.id);

    expect(event.id).toBeTruthy();
    expect(event.title).toBe(title);
    expect(event.event_type).toBe("interview");
    expect(
      event.candidate_name,
      "response should be enriched with candidate_name",
    ).toContain("Calendar"); // lastname match

    // 3. Verify event widoczny w GET /api/calendar/events.
    // Range queries akceptują from/to — daję bezpieczny ±2h zakres.
    const from = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const to = new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString();
    const list = await request.get(
      `/api/calendar/events?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&event_type=interview`,
    );
    expect(list.ok()).toBe(true);
    const events = await list.json();
    const items = Array.isArray(events) ? events : (events.items ?? []);
    const ourEvent = items.find((e: any) => e.id === event.id);
    expect(
      ourEvent,
      `created event ${event.id} must appear in GET /calendar/events list`,
    ).toBeTruthy();
    expect(ourEvent.event_type).toBe("interview");
  });
});

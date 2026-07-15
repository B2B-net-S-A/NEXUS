import { describe, expect, it } from "vitest";

import {
  normalizeTraffitIntegrationConflict,
  normalizeTraffitIntegrationEvent,
  normalizeTraffitIntegrationStatus,
} from "@/lib/api";
import {
  formatLagSeconds,
  getTraffitHealthPresentation,
} from "@/lib/traffit-integration";

function healthyStatus() {
  return normalizeTraffitIntegrationStatus({
    enabled: true,
    outbound_enabled: true,
    inbound_apply_enabled: true,
    poll_enabled: true,
    webhook_accept_enabled: true,
    leader: { owner_id: "worker-a", expires_at: "2026-07-14T10:01:00Z" },
    queues: {},
    streams: [
      {
        phase: "candidates",
        last_status: "success",
        lag_seconds: 120,
        consecutive_failures: 0,
      },
    ],
  });
}

describe("Traffit integration status", () => {
  it("normalizes a partial response without throwing", () => {
    expect(normalizeTraffitIntegrationStatus({ enabled: true })).toMatchObject({
      enabled: true,
      conflicts_open: 0,
      leader: null,
      queues: { inbox_pending: 0, outbox_pending: 0, dead_letter: 0 },
      streams: [],
    });
  });

  it("marks a healthy stream as healthy", () => {
    expect(getTraffitHealthPresentation(healthyStatus()).kind).toBe("healthy");
  });

  it("prioritizes dead-letter errors over a healthy lag", () => {
    const status = healthyStatus();
    status.queues.dead_letter = 2;
    expect(getTraffitHealthPresentation(status).kind).toBe("error");
  });

  it("marks lag over the 15 minute SLO as degraded", () => {
    const status = healthyStatus();
    status.streams[0].lag_seconds = 901;
    expect(getTraffitHealthPresentation(status).kind).toBe("degraded");
  });

  it("normalizes partial queue rows to render-safe values", () => {
    expect(normalizeTraffitIntegrationEvent({ id: 12 })).toMatchObject({
      id: "12",
      direction: "unknown",
      status: "unknown",
      attempts: 0,
    });
    expect(normalizeTraffitIntegrationConflict({ nexus_entity_id: 42 })).toMatchObject({
      nexus_entity_id: "42",
      entity_type: "unknown",
      status: "open",
    });
  });
});

describe("formatLagSeconds", () => {
  it.each([
    [null, "—"],
    [18, "18 s"],
    [61, "2 min"],
    [3660, "1 h 1 min"],
    [90_000, "1 d 1 h"],
  ])("formats %s seconds", (seconds, expected) => {
    expect(formatLagSeconds(seconds)).toBe(expected);
  });
});

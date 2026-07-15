"use client";

import {
  TraffitIntegrationPanel,
  type TraffitIntegrationMockData,
} from "@/components/settings/TraffitIntegrationPanel";

const NOW = "2026-07-14T12:00:00Z";

const MOCK_DATA: TraffitIntegrationMockData = {
  status: {
    enabled: true,
    dry_run: false,
    inbound_apply_enabled: true,
    outbound_enabled: true,
    webhook_accept_enabled: true,
    poll_enabled: true,
    paused: { inbound: false, outbound: false, poll: false },
    leader: {
      owner_id: "nexus-backend-1",
      expires_at: "2026-07-14T12:01:30Z",
    },
    queues: {
      inbox_pending: 3,
      outbox_pending: 5,
      dead_letter: 0,
      oldest_inbox_at: "2026-07-14T11:57:00Z",
      oldest_outbox_at: "2026-07-14T11:55:00Z",
    },
    conflicts_open: 2,
    last_reconcile_at: "2026-07-14T02:08:00Z",
    streams: [
      {
        phase: "candidates",
        last_success_at: "2026-07-14T11:58:00Z",
        last_status: "success",
        lag_seconds: 118,
        consecutive_failures: 0,
      },
      {
        phase: "activities_notes",
        last_success_at: "2026-07-14T11:56:00Z",
        last_status: "success",
        lag_seconds: 241,
        consecutive_failures: 0,
      },
      {
        phase: "assignments_stages",
        last_success_at: "2026-07-14T11:54:00Z",
        last_status: "success",
        lag_seconds: 356,
        consecutive_failures: 0,
      },
      {
        phase: "files",
        last_success_at: "2026-07-14T11:52:00Z",
        last_status: "success",
        lag_seconds: 472,
        consecutive_failures: 0,
      },
    ],
  },
  conflicts: {
    total: 2,
    items: [
      {
        id: "conflict-01",
        entity_type: "candidate",
        nexus_entity_id: "18424",
        external_id: "562901",
        field_path: "candidate.email",
        conflict_type: "same_field_changed",
        base_value: "anna.kowalska@old.example",
        local_value: "anna.kowalska@nexus.example",
        remote_value: "a.kowalska@traffit.example",
        status: "open",
        created_at: "2026-07-14T11:42:00Z",
        resolved_at: null,
      },
      {
        id: "conflict-02",
        entity_type: "candidate_stage",
        nexus_entity_id: "98712",
        external_id: "80441",
        field_path: "stage",
        conflict_type: "divergent_stage_move",
        base_value: "Weryfikacja",
        local_value: "Rekomendacja",
        remote_value: "Odrzucony",
        status: "open",
        created_at: "2026-07-14T11:36:00Z",
        resolved_at: null,
      },
    ],
  },
  events: {
    total: 4,
    items: [
      {
        id: "event-01",
        direction: "outbound",
        event_type: "candidate.updated",
        aggregate_type: "candidate",
        aggregate_id: "18424",
        status: "completed",
        attempts: 1,
        next_attempt_at: null,
        last_error: null,
        created_at: "2026-07-14T11:59:00Z",
        processed_at: NOW,
      },
      {
        id: "event-02",
        direction: "inbound",
        event_type: "note.created",
        aggregate_type: "candidate",
        aggregate_id: "18507",
        status: "completed",
        attempts: 1,
        next_attempt_at: null,
        last_error: null,
        created_at: "2026-07-14T11:56:00Z",
        processed_at: "2026-07-14T11:56:12Z",
      },
      {
        id: "event-03",
        direction: "outbound",
        event_type: "stage.moved",
        aggregate_type: "candidate_stage",
        aggregate_id: "98712",
        status: "pending",
        attempts: 0,
        next_attempt_at: "2026-07-14T12:00:30Z",
        last_error: null,
        created_at: "2026-07-14T11:55:00Z",
        processed_at: null,
      },
      {
        id: "event-04",
        direction: "outbound",
        event_type: "file.uploaded",
        aggregate_type: "candidate_document",
        aggregate_id: "43811",
        status: "failed",
        attempts: 2,
        next_attempt_at: "2026-07-14T12:02:00Z",
        last_error: "Traffit API timeout; zaplanowano automatyczny retry.",
        created_at: "2026-07-14T11:51:00Z",
        processed_at: null,
      },
    ],
  },
};

export default function TraffitPreviewPage() {
  return (
    <main className="min-h-screen bg-background px-6 py-8">
      <TraffitIntegrationPanel isAdmin mockData={MOCK_DATA} />
    </main>
  );
}

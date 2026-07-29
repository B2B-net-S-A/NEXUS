"use client";

import { ContactQueueWorkspace } from "@/components/candidate-contact/ContactQueueWorkspace";
import type {
  CandidateContactCase,
  CandidateContactQueueResponse,
} from "@/lib/candidate-contact";

const PREVIEW_QUEUE: CandidateContactQueueResponse = {
  utilization: { used: 18, capacity: 20 },
  next_cursor: null,
  items: [
    {
      id: 401,
      status: "queued",
      due_at: "2026-07-28T16:00:00Z",
      callback_at: null,
      attempts_in_cycle: 0,
      version: 3,
      owner: { id: 11, name: "Marta Nowak" },
      candidate: {
        id: 1001,
        name: "Alicja",
        lastname: "Zielińska",
        phone: "+48 500 100 200",
        email: "alicja@example.com",
        current_role: "Senior Java Developer",
      },
      opportunities: [
        {
          job_id: 201,
          job_title: "Senior Java Developer",
          client_name: "Bank Północny",
          owner: { id: 11, name: "Marta Nowak" },
        },
        {
          job_id: 202,
          job_title: "Backend Tech Lead",
          client_name: "Fintech One",
          owner: { id: 12, name: "Piotr Zieliński" },
        },
        {
          job_id: 203,
          job_title: "Solution Architect",
          client_name: "Retail Labs",
          owner: { id: 13, name: "Ewa Maj" },
        },
      ],
    },
    {
      id: 402,
      status: "callback_due",
      due_at: "2026-07-29T08:00:00Z",
      callback_at: "2026-07-29T08:30:00Z",
      attempts_in_cycle: 1,
      version: 7,
      owner: { id: 11, name: "Marta Nowak" },
      candidate: {
        id: 1002,
        name: "Tomasz",
        lastname: "Kowalski",
        phone: "+48 600 200 300",
        email: "tomasz@example.com",
        current_role: "Cloud Architect",
      },
      opportunities: [
        {
          job_id: 204,
          job_title: "Cloud Architect",
          client_name: "Energy Cloud",
          owner: { id: 11, name: "Marta Nowak" },
        },
      ],
    },
    {
      id: 403,
      status: "blocked_no_phone",
      due_at: null,
      callback_at: null,
      attempts_in_cycle: 0,
      version: 1,
      owner: null,
      candidate: {
        id: 1003,
        name: "Julia",
        lastname: "Wiśniewska",
        phone: null,
        email: "julia@example.com",
        current_role: "Data Engineer",
      },
      opportunities: [
        {
          job_id: 205,
          job_title: "Senior Data Engineer",
          client_name: "Data Works",
          owner: { id: 14, name: "Jan Lis" },
        },
      ],
    },
  ],
};

async function previewSubmit(
  caseId: number,
): Promise<CandidateContactCase> {
  const item = PREVIEW_QUEUE.items.find((entry) => entry.id === caseId);
  if (!item) throw new Error("Nie znaleziono przypadku w preview.");
  return { ...item, status: "handoff_pending", version: item.version + 1 };
}

export default function ContactQueuePreviewPage() {
  return (
    <main className="min-h-screen bg-background app-shell-root">
      <ContactQueueWorkspace
        initialData={PREVIEW_QUEUE}
        now="2026-07-28T17:30:00+02:00"
        featureEnabledOverride
        submitAttempt={previewSubmit}
      />
    </main>
  );
}

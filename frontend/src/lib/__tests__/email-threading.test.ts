import { describe, it, expect } from "vitest";

import type { EmailMessage } from "@/lib/api";
import {
  MAX_DEPTH,
  buildThreadTree,
  flattenThread,
} from "@/lib/email-threading";

function makeEmail(id: number, sentAt: string | null, receivedAt: string): EmailMessage {
  return {
    id,
    m365_message_id: `msg-${id}`,
    m365_conversation_id: "conv-1",
    subject: `Re: subject ${id}`,
    from_address: id % 2 === 0 ? "recruiter@b2bnet.pl" : "candidate@example.com",
    from_name: id % 2 === 0 ? "Recruiter" : "Candidate",
    to_addresses: [],
    cc_addresses: [],
    body_html: null,
    body_text: null,
    body_preview: `preview ${id}`,
    sent_at: sentAt,
    received_at: receivedAt,
    direction: id % 2 === 0 ? "sent" : "received",
    has_attachments: false,
    is_read: true,
    is_archived: false,
    is_private_filtered: false,
    match_method: "strict",
    match_confidence: 1.0,
  };
}

describe("buildThreadTree", () => {
  it("returns empty array for empty input", () => {
    expect(buildThreadTree([])).toEqual([]);
  });

  it("returns single root with no children for one email", () => {
    const email = makeEmail(1, "2026-05-14T10:00:00Z", "2026-05-14T10:00:01Z");
    const tree = buildThreadTree([email]);
    expect(tree).toHaveLength(1);
    expect(tree[0].email.id).toBe(1);
    expect(tree[0].children).toEqual([]);
  });

  it("chains emails chronologically regardless of input order", () => {
    const e1 = makeEmail(1, "2026-05-14T10:00:00Z", "2026-05-14T10:00:01Z");
    const e2 = makeEmail(2, "2026-05-14T11:00:00Z", "2026-05-14T11:00:01Z");
    const e3 = makeEmail(3, "2026-05-14T12:00:00Z", "2026-05-14T12:00:01Z");

    const tree = buildThreadTree([e3, e1, e2]);

    expect(tree).toHaveLength(1);
    expect(tree[0].email.id).toBe(1);
    expect(tree[0].children).toHaveLength(1);
    expect(tree[0].children[0].email.id).toBe(2);
    expect(tree[0].children[0].children[0].email.id).toBe(3);
  });

  it("falls back to received_at when sent_at is null", () => {
    const e1 = makeEmail(1, null, "2026-05-14T10:00:00Z");
    const e2 = makeEmail(2, null, "2026-05-14T09:00:00Z");

    const tree = buildThreadTree([e1, e2]);

    expect(tree[0].email.id).toBe(2);
    expect(tree[0].children[0].email.id).toBe(1);
  });
});

describe("flattenThread", () => {
  it("emits depth-first list with correct depths", () => {
    const e1 = makeEmail(1, "2026-05-14T10:00:00Z", "2026-05-14T10:00:01Z");
    const e2 = makeEmail(2, "2026-05-14T11:00:00Z", "2026-05-14T11:00:01Z");
    const e3 = makeEmail(3, "2026-05-14T12:00:00Z", "2026-05-14T12:00:01Z");

    const flat = flattenThread(buildThreadTree([e1, e2, e3]));

    expect(flat).toEqual([
      { email: e1, depth: 0, hasChildren: true },
      { email: e2, depth: 1, hasChildren: true },
      { email: e3, depth: 2, hasChildren: false },
    ]);
  });

  it("caps depth at MAX_DEPTH for long chains", () => {
    const emails = Array.from({ length: MAX_DEPTH + 5 }, (_, i) =>
      makeEmail(i, `2026-05-14T10:${String(i).padStart(2, "0")}:00Z`, `2026-05-14T10:${String(i).padStart(2, "0")}:01Z`),
    );

    const flat = flattenThread(buildThreadTree(emails));

    expect(flat[flat.length - 1].depth).toBe(MAX_DEPTH);
    // First MAX_DEPTH + 1 items keep increasing depth (0..MAX_DEPTH); the rest stay clamped.
    expect(flat[MAX_DEPTH].depth).toBe(MAX_DEPTH);
    expect(flat[MAX_DEPTH + 1].depth).toBe(MAX_DEPTH);
  });

  it("returns single node with depth 0 for one-email thread", () => {
    const e1 = makeEmail(1, "2026-05-14T10:00:00Z", "2026-05-14T10:00:01Z");
    const flat = flattenThread(buildThreadTree([e1]));
    expect(flat).toEqual([{ email: e1, depth: 0, hasChildren: false }]);
  });
});

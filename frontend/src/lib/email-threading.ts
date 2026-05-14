/**
 * Build a parent/child tree out of a flat list of emails in one conversation.
 *
 * Phase 5.3 — the Graph sync does not (yet) persist `In-Reply-To` headers, so
 * we use a chronological heuristic: sort by sent_at ASC (fallback received_at),
 * then every message's parent is the immediately preceding message in the same
 * conversation. This produces a degenerate chain (depth = N - 1 for N
 * messages) but renders correctly as Outlook-style nested replies for the
 * common back-and-forth case, which is the bulk of recruiter threads.
 *
 * `MAX_DEPTH` caps recursion in the renderer; beyond it new replies are
 * flattened to the cap level (still visually grouped but no further indent).
 */
import type { EmailMessage } from "@/lib/api";

export const MAX_DEPTH = 20;

export interface ThreadNode {
  email: EmailMessage;
  children: ThreadNode[];
}

export interface FlatThreadNode {
  email: EmailMessage;
  depth: number;
  hasChildren: boolean;
}

function timestamp(email: EmailMessage): number {
  // sent_at is the canonical send-side clock; received_at is recipient-side.
  // For inbound messages sent_at is usually present; for ATS-sent messages it
  // can be null until the next delta sync writes back the Graph copy.
  const t = email.sent_at ?? email.received_at;
  const ms = new Date(t).getTime();
  return Number.isFinite(ms) ? ms : 0;
}

export function buildThreadTree(emails: EmailMessage[]): ThreadNode[] {
  if (emails.length === 0) return [];

  const sorted = [...emails].sort((a, b) => timestamp(a) - timestamp(b));

  const nodes: ThreadNode[] = sorted.map((email) => ({
    email,
    children: [],
  }));

  // Linear chain — each node parents the next chronological message.
  for (let i = 1; i < nodes.length; i++) {
    nodes[i - 1].children.push(nodes[i]);
  }

  return [nodes[0]];
}

/**
 * Walk the tree in depth-first order and emit a flat list with the visual
 * depth for each node. The renderer uses `depth` (capped at MAX_DEPTH) to
 * compute Tailwind padding-left and decide whether a left connector border
 * should be drawn.
 */
export function flattenThread(roots: ThreadNode[]): FlatThreadNode[] {
  const out: FlatThreadNode[] = [];
  const walk = (node: ThreadNode, depth: number) => {
    const cappedDepth = Math.min(depth, MAX_DEPTH);
    out.push({
      email: node.email,
      depth: cappedDepth,
      hasChildren: node.children.length > 0,
    });
    for (const child of node.children) {
      walk(child, depth + 1);
    }
  };
  for (const root of roots) {
    walk(root, 0);
  }
  return out;
}

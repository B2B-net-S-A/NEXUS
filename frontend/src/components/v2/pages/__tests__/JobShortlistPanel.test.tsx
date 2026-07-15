import * as React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShortlistEntry } from "@/lib/candidate-search-api";

const list = vi.fn();
const update = vi.fn();
const remove = vi.fn();
const promote = vi.fn();

vi.mock("@/lib/candidate-search-api", () => ({
  shortlistApi: {
    list: (...a: unknown[]) => list(...a),
    update: (...a: unknown[]) => update(...a),
    remove: (...a: unknown[]) => remove(...a),
    promote: (...a: unknown[]) => promote(...a),
  },
}));

// Import AFTER the mock is registered.
import { JobShortlistPanel } from "@/components/v2/pages/JobShortlistPanel";

function entry(over: Partial<ShortlistEntry> = {}): ShortlistEntry {
  return {
    id: 1,
    job_id: 10,
    candidate_id: 5,
    candidate_name: "Anna",
    candidate_lastname: "Kowalska",
    evaluation_status: "do_oceny",
    outreach_status: "nie_kontaktowano",
    version: 1,
    score_snapshot: 82,
    ...over,
  };
}

describe("JobShortlistPanel", () => {
  beforeEach(() => {
    list.mockReset();
    promote.mockReset();
  });

  it("renders nothing when the shortlist is empty", async () => {
    list.mockResolvedValue([]);
    const { container } = render(<JobShortlistPanel jobId={10} />);
    await waitFor(() => expect(list).toHaveBeenCalledWith(10));
    expect(container.textContent).toBe("");
  });

  it("lists entries with a promote action and the count", async () => {
    list.mockResolvedValue([entry()]);
    render(<JobShortlistPanel jobId={10} />);
    await waitFor(() =>
      expect(screen.getByText("Anna Kowalska")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Shortlista/)).toBeInTheDocument();
    expect(screen.getByText("(1)")).toBeInTheDocument();
    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText("Do rekrutacji")).toBeInTheDocument();
  });

  it("shows 'w rekrutacji' instead of promote for a promoted entry", async () => {
    list.mockResolvedValue([
      entry({ promoted_to_pipeline_at: "2026-07-15T00:00:00Z" }),
    ]);
    render(<JobShortlistPanel jobId={10} />);
    await waitFor(() =>
      expect(screen.getByText("w rekrutacji")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Do rekrutacji")).not.toBeInTheDocument();
  });
});

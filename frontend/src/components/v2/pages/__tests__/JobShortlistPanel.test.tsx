import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

// ── M4 PR-03 (audyt P2.8): taksonomia błędów zamiast maskowania ─────────────

function axiosErr(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: detail ? { detail } : {} },
  });
}

describe("JobShortlistPanel — error taxonomy (M4 PR-03)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("błąd pobrania pokazuje stan błędu z retry, nie znika jak pusta lista", async () => {
    list.mockRejectedValueOnce(axiosErr(500));
    list.mockResolvedValueOnce([entry()]);
    render(<JobShortlistPanel jobId={10} />);

    expect(
      await screen.findByText("Nie udało się pobrać shortlisty.")
    ).toBeTruthy();
    const retry = screen.getByRole("button", { name: "Spróbuj ponownie" });
    retry.click();
    expect(await screen.findByText(/Kowalska/)).toBeTruthy();
  });

  it("PATCH 403 to komunikat o uprawnieniach, nie fałszywy konflikt", async () => {
    list.mockResolvedValue([entry()]);
    update.mockRejectedValueOnce(axiosErr(403));
    render(<JobShortlistPanel jobId={10} />);
    const select = await screen.findByLabelText("Ocena");
    fireEvent.change(select, { target: { value: "zatwierdzony" } });
    expect(
      await screen.findByText("Brak uprawnień do zmiany tego wpisu.")
    ).toBeTruthy();
  });

  it("PATCH 409 nadal komunikuje konflikt równoległej edycji", async () => {
    list.mockResolvedValue([entry()]);
    update.mockRejectedValueOnce(axiosErr(409));
    render(<JobShortlistPanel jobId={10} />);
    const select = await screen.findByLabelText("Ocena");
    fireEvent.change(select, { target: { value: "zatwierdzony" } });
    expect(
      await screen.findByText("Wpis zmieniony w innym miejscu — lista odświeżona.")
    ).toBeTruthy();
  });

  it("promote pokazuje detail z backendu (np. eligibility 409)", async () => {
    list.mockResolvedValue([entry()]);
    promote.mockRejectedValueOnce(
      axiosErr(409, "Kandydat ma konflikt NDA z tym klientem.")
    );
    render(<JobShortlistPanel jobId={10} />);
    const btn = await screen.findByRole("button", { name: /Do rekrutacji/ });
    btn.click();
    expect(
      await screen.findByText("Kandydat ma konflikt NDA z tym klientem.")
    ).toBeTruthy();
  });

  it("błąd usunięcia jest widoczny, nie połknięty", async () => {
    list.mockResolvedValue([entry()]);
    remove.mockRejectedValueOnce(axiosErr(500));
    render(<JobShortlistPanel jobId={10} />);
    const btn = await screen.findByLabelText(/Usuń Anna z shortlisty/);
    btn.click();
    expect(
      await screen.findByText("Nie udało się usunąć wpisu.")
    ).toBeTruthy();
  });
});

import * as React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MarketTrainerApplication } from "@/lib/api/trainings";

import { MarketTrainerCandidates } from "../MarketTrainerCandidates";
import { actionsFor, countByStatus, topicsLine } from "../market-trainer-model";

function application(extra: Partial<MarketTrainerApplication> = {}): MarketTrainerApplication {
  return {
    id: 1,
    full_name: "Anna Przykładowa",
    email: "anna@example.com",
    linkedin: "https://linkedin.com/in/anna-przykladowa",
    topics: ["Kubernetes"],
    other_topic: "Rust w systemach wbudowanych",
    first_training: "Kafka od środka",
    experience: "Warsztaty od 2019.",
    sample_url: "https://example.com/program.pdf",
    contract_id: null,
    status: "new",
    status_note: "",
    status_changed_at: null,
    submissions: 1,
    created_at: "2026-11-28T10:00:00Z",
    updated_at: "2026-11-28T10:00:00Z",
    ...extra,
  };
}

describe("market-trainer-model", () => {
  it("zna przejścia: nowe → rozmowa → baza / odrzucone", () => {
    expect(actionsFor("new").map((a) => a.to)).toEqual(["interview", "rejected"]);
    expect(actionsFor("interview").map((a) => a.to)).toEqual(["accepted", "rejected"]);
    expect(actionsFor("accepted").map((a) => a.to)).toEqual(["rejected"]);
    expect(actionsFor("rejected").map((a) => a.to)).toEqual(["new"]);
  });

  it("dokleja własny temat na końcu i liczy statusy", () => {
    expect(topicsLine(application())).toBe("Kubernetes, Rust w systemach wbudowanych");
    expect(topicsLine(application({ other_topic: null }))).toBe("Kubernetes");
    const counts = countByStatus([
      application(),
      application({ id: 2, status: "accepted" }),
      application({ id: 3 }),
    ]);
    expect(counts).toEqual({ new: 2, interview: 0, accepted: 1, rejected: 0 });
  });
});

describe("MarketTrainerCandidates", () => {
  it("pokazuje nowe, a link spoza http(s) zostaje tekstem", () => {
    render(
      <MarketTrainerCandidates
        applications={[
          application({ sample_url: "javascript:alert(1)", linkedin: null }),
          application({ id: 2, full_name: "Jan Testowy", status: "accepted" }),
        ]}
        busy={false}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Anna Przykładowa")).toBeInTheDocument();
    expect(screen.queryByText("Jan Testowy")).not.toBeInTheDocument();
    expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
    expect(screen.getByRole("button", { name: /W bazie trenerów\s*1/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("zmiana stanu pyta o notatkę i oddaje ją wołającemu", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MarketTrainerCandidates applications={[application()]} busy={false} onChange={onChange} />,
    );

    await user.click(screen.getByRole("button", { name: "Umów rozmowę" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Notatka"), "Wtorek 10:00");
    await user.click(within(dialog).getByRole("button", { name: "Umów rozmowę" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1 }),
      "interview",
      "Wtorek 10:00",
    );
  });

  it("notatka jest opcjonalna: zmiana przechodzi bez wpisu", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MarketTrainerCandidates applications={[application()]} busy={false} onChange={onChange} />,
    );

    await user.click(screen.getByRole("button", { name: "Odrzuć" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Odrzuć" });
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), "rejected", "");
  });

  it("oznacza konsultanta z kontraktem", () => {
    render(
      <MarketTrainerCandidates
        applications={[application({ contract_id: 42 })]}
        busy={false}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("nasz konsultant")).toBeInTheDocument();
  });
});

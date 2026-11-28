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
    panel: {
      company_name: "",
      nip: null,
      regon: "",
      company_address: "",
      panel_email: null,
      panel_open: false,
      panel_opened_at: null,
      panel_closed_at: null,
    },
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

  it("trener z bazy bez panelu: „Otwórz panel trenera” pyta o dane firmy", async () => {
    const user = userEvent.setup();
    const onOpenPanel = vi.fn().mockResolvedValue(true);
    render(
      <MarketTrainerCandidates
        applications={[application({ status: "accepted" })]}
        busy={false}
        onChange={vi.fn()}
        onOpenPanel={onOpenPanel}
        onClosePanel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /W bazie trenerów/ }));
    await user.click(screen.getByRole("button", { name: "Otwórz panel trenera" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("E-mail do panelu")).toHaveValue("anna@example.com");
    await user.type(within(dialog).getByLabelText("NIP firmy"), "1234563218");
    await user.type(within(dialog).getByLabelText("Nazwa firmy"), "Przykładowa Szkoła");
    await user.type(within(dialog).getByLabelText("Adres siedziby"), "ul. Prosta 1, 00-001 Warszawa");
    await user.click(within(dialog).getByRole("button", { name: "Otwórz panel i wyślij link" }));

    expect(onOpenPanel).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1 }),
      expect.objectContaining({ nip: "1234563218", panel_email: "anna@example.com" }),
    );
  });

  it("otwarty panel daje „Zamów szkolenie” dla tego trenera", async () => {
    const user = userEvent.setup();
    render(
      <MarketTrainerCandidates
        applications={[
          application({
            status: "accepted",
            panel: {
              company_name: "Przykładowa Szkoła",
              nip: "1234563218",
              regon: "",
              company_address: "ul. Prosta 1, 00-001 Warszawa",
              panel_email: "anna@example.com",
              panel_open: true,
              panel_opened_at: "2026-11-28T10:00:00Z",
              panel_closed_at: null,
            },
          }),
        ]}
        busy={false}
        onChange={vi.fn()}
        onOpenPanel={vi.fn()}
        onClosePanel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /W bazie trenerów/ }));
    expect(screen.getByRole("link", { name: "Zamów szkolenie" })).toHaveAttribute(
      "href",
      "/trainings/new?market=1",
    );
    expect(screen.getByText(/Panel otwarty/)).toBeInTheDocument();
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

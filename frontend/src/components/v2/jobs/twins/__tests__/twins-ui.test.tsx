import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { OpenSimilarItem, TwinJobBrief } from "@/lib/job-twins-api";

import { OpenSimilarList } from "../OpenSimilarTile";
import { TwinSuggestionList } from "../TwinSuggestionsButton";

function brief(over: Partial<TwinJobBrief>): TwinJobBrief {
  return {
    id: 1,
    title: "Programista Python",
    reference_number: null,
    client_reference: "ZOB-2964",
    client_id: 1,
    client_name: "Klient Demo",
    delivery_lead_id: 1,
    delivery_lead_name: "Anna K.",
    status: "published",
    is_open: true,
    p1: false,
    budget_min_hourly: null,
    budget_hourly: 110,
    remote_policy: "remote",
    onsite_days_per_week: null,
    onsite_days_per_month: null,
    location: null,
    people_count: 11,
    ...over,
  };
}

function item(over: Partial<OpenSimilarItem>): OpenSimilarItem {
  return { ...brief(over), similarity: 76, twin: false, can_twin: false, twin_limit_reached: false, ...over };
}

describe("Otwarte podobne (0614)", () => {
  it("shows P1, the twin button only where the viewer may link, and unlink for a twin", () => {
    const onTwin = vi.fn();
    const onUnlink = vi.fn();
    render(
      <OpenSimilarList
        items={[
          item({ id: 3, p1: true, client_reference: "ZOB-3001" }),
          item({ id: 2, can_twin: true, client_reference: "ZOB-2904" }),
          item({ id: 4, twin: true, client_reference: "ZOB-2964" }),
        ]}
        onTwin={onTwin}
        onUnlink={onUnlink}
      />,
    );
    const p1 = screen.getByTestId("open-similar-3");
    expect(p1).toHaveTextContent("P1");
    expect(p1.querySelector("button")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Bliźniak$/ }));
    expect(onTwin).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
    fireEvent.click(screen.getByRole("button", { name: /Rozłącz/ }));
    expect(onUnlink).toHaveBeenCalledWith(expect.objectContaining({ id: 4 }));
    expect(screen.getAllByText(/zdalnie · do 110 zł\/h/)).toHaveLength(3);
  });
});

describe("Możliwe bliźniaki dla HoR (0614)", () => {
  it("lists both requests with their DL and lets you link or dismiss", () => {
    const onLink = vi.fn();
    const onDismiss = vi.fn();
    const pair = {
      similarity: 84,
      job: brief({ id: 10, client_reference: "ZOB-2852", client_name: "Bank A", delivery_lead_name: "Martyna W." }),
      other: brief({ id: 11, client_reference: "6755", client_name: "Bank B", delivery_lead_name: "Klaudia U.", budget_hourly: null }),
    };
    render(<TwinSuggestionList items={[pair]} onLink={onLink} onDismiss={onDismiss} />);
    expect(screen.getByText(/DL Martyna W\./)).toBeInTheDocument();
    expect(screen.getByText(/brak budżetu/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Połącz/ }));
    fireEvent.click(screen.getByRole("button", { name: "To nie bliźniak" }));
    expect(onLink).toHaveBeenCalledWith(pair);
    expect(onDismiss).toHaveBeenCalledWith(pair);
  });
});

describe("Zasady bliźniaków przy parze (29.10.2026)", () => {
  it("shows ✕ for failed required rules and ⚠ for warnings, and the compliance note", async () => {
    const { RuleChips } = await import("../OpenSimilarTile");
    const { TwinRulesCompliance } = await import("../TwinLinkDialog");
    const crit = { key: "critical" as const, label: "Umiejętności krytyczne", mode: "required" as const, ok: false, detail: "„analiza systemowa” — nie ma w drugiej" };
    const mode = { key: "work_mode" as const, label: "Tryb pracy", mode: "warning" as const, ok: false, detail: "1 dni z biura vs zdalnie → osobna stawka" };
    const budget = { key: "budget" as const, label: "Budżet", mode: "warning" as const, ok: true, detail: "do 110 vs brak" };
    const { unmount } = render(<RuleChips failures={[crit]} warnings={[mode]} />);
    expect(screen.getByText("✕ umiejętności krytyczne")).toBeInTheDocument();
    expect(screen.getByText("⚠ tryb pracy")).toBeInTheDocument();
    unmount();
    render(<TwinRulesCompliance checks={[crit, mode, budget]} />);
    expect(screen.getByTestId("twin-rules-compliance")).toHaveTextContent("✕");
    expect(screen.getByRole("note")).toHaveTextContent("nie trafia na listę „Możliwe bliźniaki”. Połączyć ją możesz");
  });
});

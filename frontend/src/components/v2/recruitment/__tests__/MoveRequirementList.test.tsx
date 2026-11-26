import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MoveRequirementList } from "@/components/v2/recruitment/MoveRequirementList";
import type { MoveRequirementItem } from "@/lib/api/moveRequirements";

const DEAL_BREAKER: MoveRequirementItem = {
  key: "deal_breaker",
  label: "Odpowiedź narusza „Odpada, gdy…”",
  status: "missing",
  blocking: false,
  action: { kind: "reject", label: "Odrzuć z powodem", stage_id: 5, note: "Odpada, gdy: brak Javy" },
};

const REMINDER: MoveRequirementItem = {
  key: "availability",
  label: "Dostępność",
  status: "missing",
  blocking: false,
  action: null,
};

describe("MoveRequirementList", () => {
  it("naruszone „Odpada, gdy…” ma ton ostrzeżenia, zwykłe przypomnienie nie", () => {
    render(
      <MoveRequirementList items={[DEAL_BREAKER, REMINDER]} askedDuringMove onAction={vi.fn()} />,
    );
    const warning = screen.getByText("Odpowiedź narusza „Odpada, gdy…”").closest("li");
    expect(warning).toHaveAttribute("data-tone", "warning");
    expect(warning?.className).toContain("bg-warning-muted");
    expect(screen.getByLabelText("Ostrzeżenie")).toBeTruthy();

    const reminder = screen.getByText("Dostępność").closest("li");
    expect(reminder).not.toHaveAttribute("data-tone");
    expect(reminder?.className).not.toContain("bg-warning-muted");
  });

  it("ten sam klucz w dwóch kolumnach drogi to dwa wiersze bez ostrzeżenia Reacta (26.11.2026)", () => {
    // Odpowiedź stagingu dla „Zweryfikowany” → „CV wysłane” u klienta
    // z formularzem: `client_form` z kolumny „QC CV” i z „CV wysłane”.
    const items: MoveRequirementItem[] = [
      { key: "client_form", column: "cv_qc", label: "Formularz CV klienta", status: "waiting", blocking: false },
      { key: "client_score", column: "cv_qc", label: "Tabela punktowa klienta", status: "waiting", blocking: false },
      { key: "client_form", column: "cv_sent", label: "Formularz CV klienta", status: "waiting", blocking: false },
      { key: "client_rate", column: "cv_sent", label: "Stawka do klienta", status: "waiting", blocking: false },
    ];
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(<MoveRequirementList items={items} askedDuringMove onAction={vi.fn()} />);
      const sameKey = errors.mock.calls.filter((call) => String(call[0]).includes("same key"));
      expect(sameKey).toEqual([]);
    } finally {
      errors.mockRestore();
    }
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getAllByText("Formularz CV klienta")).toHaveLength(2);
  });

  it("przycisk „Odrzuć z powodem” oddaje akcję z notatką", () => {
    const onAction = vi.fn();
    render(<MoveRequirementList items={[DEAL_BREAKER]} askedDuringMove onAction={onAction} />);
    screen.getByRole("button", { name: "Odrzuć z powodem" }).click();
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ kind: "reject", note: "Odpada, gdy: brak Javy" }));
  });
});

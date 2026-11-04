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

  it("przycisk „Odrzuć z powodem” oddaje akcję z notatką", () => {
    const onAction = vi.fn();
    render(<MoveRequirementList items={[DEAL_BREAKER]} askedDuringMove onAction={onAction} />);
    screen.getByRole("button", { name: "Odrzuć z powodem" }).click();
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ kind: "reject", note: "Odpada, gdy: brak Javy" }));
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { P0TopbarTrigger } from "@/components/v2/jobs/p0/P0TopbarButton";

// Układ mierzy e2e/responsive-preview.spec.ts (jsdom nie liczy CSS). Tu to, co
// test w przeglądarce widzi tylko nocą: forma zwarta nie zabiera nazw i funkcji.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => ({ "candidate.create": true }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/AppShell", () => ({
  AddCandidateModal: () => null,
  AddClientModal: () => null,
  AddContactModal: () => null,
  AddMeetingModal: () => null,
}));
vi.mock("@/components/v2/modals/GenerateInviteLinkV2", () => ({
  GenerateInviteLinkV2: () => null,
}));

import { QuickActionsV2 } from "../QuickActionsV2";

describe("górny pasek — forma zwarta", () => {
  it("„+” nazywa się „Dodaj” przy każdej szerokości i trzyma się krawędzi paska", () => {
    render(<QuickActionsV2 />);
    const add = screen.getByRole("button", { name: "Dodaj" });
    expect(add).toHaveClass("sticky");
    expect(add).toHaveAttribute("title", "Dodaj");
  });

  it("konto bez prawa tworzenia nie dostaje „+”, także po zmianie przycisku", async () => {
    const capability = await import("@/hooks/useCapability");
    const spy = vi.spyOn(capability, "useCapabilities").mockReturnValue({} as never);
    render(<QuickActionsV2 />);
    expect(screen.queryByRole("button", { name: "Dodaj" })).not.toBeInTheDocument();
    spy.mockRestore();
  });

  it.each([
    [1, "P0 teraz: 1 rekrutacja"],
    [3, "P0 teraz: 3 rekrutacje"],
    [12, "P0 teraz: 12 rekrutacji"],
  ])("P0 przy %i mówi pełnym zdaniem, choć na ekranie stoi sama liczba", (count, label) => {
    render(<P0TopbarTrigger count={count} />);
    const button = screen.getByRole("button", { name: label });
    expect(button).toHaveAttribute("title", label);
    expect(button).toHaveTextContent(String(count));
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CandidateNav } from "@/components/v2/CandidateNav";
import { PinButton } from "@/components/v2/PinButton";

const pins = vi.hoisted(() => ({
  getState: vi.fn().mockResolvedValue({ data: { pinned: false } }),
  toggle: vi.fn().mockResolvedValue({ data: { pinned: true } }),
}));

vi.mock("@/lib/api", () => ({
  candidatePinsApi: pins,
}));

function expectTouchTarget(element: HTMLElement) {
  expect(element.classList.contains("min-h-11")).toBe(true);
  expect(element.classList.contains("min-w-11")).toBe(true);
}

describe("candidate profile header touch targets", () => {
  it("keeps every CandidateNav action at least 44 by 44 pixels", () => {
    render(
      <CandidateNav
        position={2}
        total={5}
        hasPrev
        hasNext
        onPrev={vi.fn()}
        onNext={vi.fn()}
        error="Nie udało się pobrać sąsiedniego kandydata"
        onRetry={vi.fn()}
        onExpand={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    for (const name of [
      "Poprzedni kandydat",
      "Następny kandydat",
      "Otwórz w pełnym widoku",
      "Zamknij profil",
      "Ponów",
    ]) {
      expectTouchTarget(screen.getByRole("button", { name }));
    }
  });

  it("keeps the icon-only pin action accessible and at least 44 by 44 pixels", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <PinButton candidateId={7} iconOnly />
      </QueryClientProvider>,
    );

    expectTouchTarget(
      await screen.findByRole("button", { name: "Przypnij kandydata" }),
    );
  });
});

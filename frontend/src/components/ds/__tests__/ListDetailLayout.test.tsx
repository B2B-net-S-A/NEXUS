import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ListDetailLayout } from "../ListDetailLayout";

function mockMedia(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

function renderAt(top: number) {
  const rect = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockReturnValue({ top, bottom: top + 500, left: 0, right: 380, width: 380, height: 500, x: 0, y: top } as DOMRect);
  render(<ListDetailLayout list={<div>tabela</div>} panel={<div>panel</div>} onClose={() => {}} panelLabel="Szczegóły" />);
  rect.mockRestore();
  return screen.getByRole("complementary", { name: "Szczegóły" });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ListDetailLayout — wysokość panelu obok tabeli", () => {
  it("panel kończy się nad dolną krawędzią okna, żeby stopka z akcjami była widoczna", () => {
    // Na liście kontraktów panel startował 200 px od góry i miał 870 px —
    // przy oknie 950 px przyciski stopki wypadały pod ekran.
    mockMedia(true);
    vi.stubGlobal("innerHeight", 950);
    const panel = renderAt(200);
    expect(panel.style.maxHeight).toBe("734px");
  });

  it("nie schodzi poniżej 360 px, gdy panel startuje nisko", () => {
    mockMedia(true);
    vi.stubGlobal("innerHeight", 700);
    const panel = renderAt(600);
    expect(panel.style.maxHeight).toBe("360px");
  });

  it("poniżej 1600 px nie ustawia wysokości (panel nachodzi na tabelę na całą wysokość)", () => {
    mockMedia(false);
    const panel = renderAt(200);
    expect(panel.style.maxHeight).toBe("");
  });
});

import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecentFactsLine } from "@/components/v2/candidates/RecentFactsLine";

describe("RecentFactsLine", () => {
  it("najnowsza informacja pierwsza, wcześniejsza za nią, każda z datą", () => {
    const onOpen = vi.fn();
    render(
      <RecentFactsLine
        onOpen={onOpen}
        facts={[
          { at: "2026-11-02T13:09:06Z", kind: "talk", text: "dostępność ASAP, 110 zł/h" },
          { at: "2026-07-30T11:12:17Z", kind: "note", text: "nie jest zainteresowany" },
        ]}
      />,
    );
    const line = screen.getByTestId("recent-facts-line");
    expect(line.textContent).toBe(
      "Ostatnio z osobą: 02.11.26 rozmowa — dostępność ASAP, 110 zł/h · wcześniej 30.07.26 notatka — „nie jest zainteresowany”",
    );
    line.click();
    expect(onOpen).toHaveBeenCalled();
  });

  it("pusta lista mówi to wprost, brak pola nie udaje pustki", () => {
    const { rerender } = render(<RecentFactsLine facts={[]} />);
    expect(screen.getByTestId("recent-facts-line").textContent).toContain("brak notatek i odrzuceń");
    rerender(<RecentFactsLine facts={undefined} />);
    expect(screen.getByTestId("recent-facts-line").textContent).toBe("Ostatnio z osobą: —");
  });
});

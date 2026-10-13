import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KpiProgressBar } from "@/components/v2/kpi/KpiProgressBar";
import type { KpiState } from "@/lib/api";

function fillClass(state: KpiState): string {
  const { unmount } = render(<KpiProgressBar progressPct={25} state={state} />);
  const fill = screen.getByRole("progressbar").firstElementChild as HTMLElement;
  const classes = fill.className;
  unmount();
  return classes;
}

describe("KpiProgressBar", () => {
  it("kolory z tokenów: zrobione, w tempie, poniżej tempa, okres zamknięty", () => {
    expect(fillClass("hit")).toContain("bg-success");
    expect(fillClass("on_track")).toContain("bg-primary");
    expect(fillClass("behind")).toContain("bg-warning");
    expect(fillClass("missed")).toContain("bg-muted-foreground/40");
  });

  it("„powyżej tempa” wygląda jak „w tempie”, nie jak cel zrobiony", () => {
    // Do 13.10.2026 jedna weryfikacja z czterech o 10:00 świeciła zielenią celu.
    expect(fillClass("ahead")).toBe(fillClass("on_track"));
    expect(fillClass("ahead")).not.toContain("bg-success");
  });

  it("kreska tempa stoi obok toru jako span (tryb Kids farbuje każdy div w torze)", () => {
    render(<KpiProgressBar progressPct={25} state="behind" expectedPct={50} />);
    const tick = screen.getByTestId("kpi-pace-tick");
    const track = screen.getByRole("progressbar");
    expect(tick.tagName).toBe("SPAN");
    expect(tick).toHaveStyle({ left: "50%" });
    expect(track.contains(tick)).toBe(false);
    expect(track.querySelectorAll(":scope > div")).toHaveLength(1);
  });

  it("bez tempa nie ma kreski, a wartość spoza skali trzyma się paska", () => {
    const { rerender } = render(<KpiProgressBar progressPct={25} state="on_track" />);
    expect(screen.queryByTestId("kpi-pace-tick")).toBeNull();
    rerender(<KpiProgressBar progressPct={25} state="on_track" expectedPct={140} />);
    expect(screen.getByTestId("kpi-pace-tick")).toHaveStyle({ left: "100%" });
  });
});

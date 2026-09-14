import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ANCHOR_PIN_CHECK_MS, ANCHOR_PIN_MAX_MS, pinAnchor } from "@/lib/anchor-pin";

/**
 * Reaudyt 14.09.2026 (R03): po skoku do `#zrodla` sekcje nad celem doczytały
 * treść i cel odjechał 3180 px pod ekran. Przypięcie ma wracać do celu, dopóki
 * układ się zmienia, i oddać sterowanie przy pierwszej akcji człowieka.
 */
describe("pinAnchor", () => {
  let top = 0;
  let target: HTMLElement;
  let scrollSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    target = document.createElement("div");
    target.id = "zrodla";
    document.body.appendChild(target);
    top = 80;
    scrollSpy = vi.fn(() => {
      top = 80;
    });
    target.scrollIntoView = scrollSpy as unknown as typeof target.scrollIntoView;
    target.getBoundingClientRect = () => ({ top }) as DOMRect;
  });

  afterEach(() => {
    target.remove();
    vi.useRealTimers();
  });

  it("wraca do celu, gdy treść nad nim urośnie", () => {
    const stop = pinAnchor("zrodla");
    expect(scrollSpy).toHaveBeenCalledTimes(1);

    top = 3260; // sekcje nad celem doczytały dane
    vi.advanceTimersByTime(ANCHOR_PIN_CHECK_MS);
    expect(scrollSpy).toHaveBeenCalledTimes(2);

    vi.advanceTimersByTime(ANCHOR_PIN_CHECK_MS * 3);
    // Bez kolejnego przesunięcia nie szarpie widokiem.
    expect(scrollSpy).toHaveBeenCalledTimes(2);
    stop();
  });

  it("oddaje sterowanie przy pierwszym kółku myszy", () => {
    pinAnchor("zrodla");
    window.dispatchEvent(new Event("wheel"));
    top = 3260;
    vi.advanceTimersByTime(ANCHOR_PIN_CHECK_MS * 5);
    expect(scrollSpy).toHaveBeenCalledTimes(1);
  });

  it("kończy się po limicie czasu", () => {
    pinAnchor("zrodla");
    vi.advanceTimersByTime(ANCHOR_PIN_MAX_MS + ANCHOR_PIN_CHECK_MS);
    top = 3260;
    vi.advanceTimersByTime(ANCHOR_PIN_CHECK_MS * 5);
    expect(scrollSpy).toHaveBeenCalledTimes(1);
  });

  it("nowa kotwica zastępuje poprzednią", () => {
    const other = document.createElement("div");
    other.id = "liga";
    other.scrollIntoView = vi.fn() as unknown as typeof other.scrollIntoView;
    other.getBoundingClientRect = () => ({ top: 80 }) as DOMRect;
    document.body.appendChild(other);

    pinAnchor("zrodla");
    pinAnchor("liga");
    top = 3260;
    vi.advanceTimersByTime(ANCHOR_PIN_CHECK_MS * 5);
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    other.remove();
  });
});

import { act, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useFillAvailableHeight } from "@/hooks/useFillAvailableHeight";

function rect(top: number, height: number): DOMRect {
  return {
    top,
    bottom: top + height,
    height,
    left: 0,
    right: 0,
    width: 0,
    x: 0,
    y: top,
    toJSON: () => ({}),
  } as DOMRect;
}

function Box({ min }: { min: number }) {
  const fill = useFillAvailableHeight(min);
  return (
    <main data-testid="scroller" style={{ overflowY: "auto" }}>
      <div data-testid="pad" style={{ paddingBottom: "24px" }}>
        <div
          data-testid="box"
          ref={fill.ref}
          data-height={fill.height ?? "unmeasured"}
        />
      </div>
    </main>
  );
}

/** Układ jak w `AppShellV2`: `<main overflow-y-auto>` pod paskiem górnym (56 px). */
function mountWithGeometry(opts: { boxTop: number; scrollTop?: number; min?: number }) {
  const original = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
    if (this.dataset.testid === "scroller") return rect(56, 634);
    if (this.dataset.testid === "box") return rect(opts.boxTop - (opts.scrollTop ?? 0), 0);
    return rect(0, 0);
  };
  const clientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this.dataset.testid === "scroller" ? 634 : 0;
    },
  });
  const scrollTop = Object.getOwnPropertyDescriptor(Element.prototype, "scrollTop");
  Object.defineProperty(Element.prototype, "scrollTop", {
    configurable: true,
    get(this: HTMLElement) {
      return this.dataset?.testid === "scroller" ? (opts.scrollTop ?? 0) : 0;
    },
  });
  const view = render(<Box min={opts.min ?? 320} />);
  const restore = () => {
    HTMLElement.prototype.getBoundingClientRect = original;
    if (clientHeight) Object.defineProperty(HTMLElement.prototype, "clientHeight", clientHeight);
    if (scrollTop) Object.defineProperty(Element.prototype, "scrollTop", scrollTop);
  };
  return { view, restore };
}

describe("useFillAvailableHeight", () => {
  it("kończy element na dolnej krawędzi przewijanego obszaru minus odstęp przodków", () => {
    // okno 690: pasek 56, obszar 634; tabela zaczyna się 170 px od góry okna.
    const { view, restore } = mountWithGeometry({ boxTop: 170 });
    try {
      // 634 − (170 − 56) − 24 = 496
      expect(view.getByTestId("box").dataset.height).toBe("496");
    } finally {
      restore();
    }
  });

  it("baner nad tabelą zmniejsza wysokość zamiast wypychać ją pod okno", () => {
    const { view, restore } = mountWithGeometry({ boxTop: 170 + 64 });
    try {
      expect(view.getByTestId("box").dataset.height).toBe("432");
    } finally {
      restore();
    }
  });

  it("przewinięcie strony nie zmienia wyniku", () => {
    const { view, restore } = mountWithGeometry({ boxTop: 170, scrollTop: 40 });
    try {
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      expect(view.getByTestId("box").dataset.height).toBe("496");
    } finally {
      restore();
    }
  });

  it("nie schodzi poniżej podłogi", () => {
    const { view, restore } = mountWithGeometry({ boxTop: 500 });
    try {
      expect(view.getByTestId("box").dataset.height).toBe("320");
    } finally {
      restore();
    }
  });
});

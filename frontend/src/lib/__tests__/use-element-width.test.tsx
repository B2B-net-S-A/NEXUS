/**
 * Pomiar szerokości elementu dla układów liczonych w JS (podgląd kandydata,
 * przegląd Delivery Leada). jsdom nie liczy układu — szerokość i
 * `ResizeObserver` są atrapami.
 */
import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useElementWidth } from "../use-element-width";

let width = 0;
let observers: Array<() => void> = [];

function resizeTo(next: number) {
  width = next;
  act(() => observers.forEach((notify) => notify()));
}

function Probe() {
  const [node, setNode] = useState<HTMLElement | null>(null);
  return (
    <div ref={setNode} data-testid="probe">
      {useElementWidth(node)}
    </div>
  );
}

beforeEach(() => {
  width = 0;
  observers = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        observers.push(callback);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.spyOn(Element.prototype, "clientWidth", "get").mockImplementation(() => width);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useElementWidth", () => {
  it("przed pierwszym pomiarem zwraca 0", () => {
    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent("0");
  });

  it("idzie za zmianą szerokości", () => {
    width = 820;
    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent("820");
    resizeTo(1240);
    expect(screen.getByTestId("probe")).toHaveTextContent("1240");
  });

  it("ukryty element (szerokość 0) zostawia ostatni pomiar", () => {
    width = 1240;
    render(<Probe />);
    resizeTo(0);
    expect(screen.getByTestId("probe")).toHaveTextContent("1240");
    resizeTo(900);
    expect(screen.getByTestId("probe")).toHaveTextContent("900");
  });
});

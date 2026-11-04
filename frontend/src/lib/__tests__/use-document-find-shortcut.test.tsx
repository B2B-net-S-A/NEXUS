import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";

import { useDocumentFindShortcut } from "@/lib/use-document-find-shortcut";

function Viewer({ label, scope }: { label: string; scope: "dialog" | "container" }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  useDocumentFindShortcut({ enabled: true, scope, containerRef, inputRef });
  return (
    <div ref={containerRef} data-testid={`box-${label}`}>
      <input ref={inputRef} aria-label={label} />
    </div>
  );
}

function pressCtrlF(): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { key: "f", ctrlKey: true, bubbles: true, cancelable: true });
  act(() => {
    document.body.dispatchEvent(event);
  });
  return event;
}

// Oryginał obok CV firmowego (03.11.2026): dwa dokumenty w jednym oknie.
// Wynik nie może zależeć od tego, który z nich zamontował się pierwszy.
describe.each([
  ["najpierw oryginał", ["container", "dialog"]],
  ["najpierw CV firmowe", ["dialog", "container"]],
] as const)("dwa dokumenty w oknie, %s", (_name, order) => {
  const renderBoth = () =>
    render(
      <>
        {order.map((scope) => (
          <Viewer key={scope} label={scope} scope={scope} />
        ))}
      </>,
    );

  it("kursor nad oryginałem: lupa oryginału", () => {
    renderBoth();
    fireEvent.pointerEnter(screen.getByTestId("box-container"));
    expect(pressCtrlF().defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(screen.getByLabelText("container"));
  });

  it("kursor poza oryginałem: lupa CV firmowego, nie wyszukiwarka przeglądarki", () => {
    renderBoth();
    expect(pressCtrlF().defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(screen.getByLabelText("dialog"));
  });

  it("po szukaniu w oryginale kursor nad CV firmowym: lupa CV firmowego", () => {
    renderBoth();
    act(() => screen.getByLabelText("container").focus());
    fireEvent.pointerEnter(screen.getByTestId("box-dialog"));
    pressCtrlF();
    expect(document.activeElement).toBe(screen.getByLabelText("dialog"));
  });

  it("fokus w oryginale bez kursora: lupa oryginału", () => {
    renderBoth();
    act(() => screen.getByLabelText("container").focus());
    pressCtrlF();
    expect(document.activeElement).toBe(screen.getByLabelText("container"));
  });
});

import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useClickOutside } from "@/lib/use-click-outside";

/** Element realnie wpięty w DOM — `contains()` musi działać na żywym drzewie. */
function mountElement(): HTMLDivElement {
  const el = document.createElement("div");
  const child = document.createElement("button");
  el.appendChild(child);
  document.body.appendChild(el);
  return el;
}

function mousedownOn(target: Node): void {
  target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("useClickOutside", () => {
  it("woła callback przy kliknięciu poza elementem", () => {
    const el = mountElement();
    const ref = { current: el as HTMLDivElement | null };
    const onOutside = vi.fn();

    renderHook(() => useClickOutside(ref, onOutside));
    mousedownOn(document.body);

    expect(onOutside).toHaveBeenCalledTimes(1);
  });

  it("NIE woła callbacku przy kliknięciu wewnątrz elementu ani w jego dziecko", () => {
    const el = mountElement();
    const ref = { current: el as HTMLDivElement | null };
    const onOutside = vi.fn();

    renderHook(() => useClickOutside(ref, onOutside));
    mousedownOn(el);
    mousedownOn(el.firstChild as Node);

    expect(onOutside).not.toHaveBeenCalled();
  });

  it("nie nasłuchuje, gdy enabled=false — i zaczyna, gdy zrobi się true", () => {
    const el = mountElement();
    const ref = { current: el as HTMLDivElement | null };
    const onOutside = vi.fn();

    const { rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useClickOutside(ref, onOutside, enabled),
      { initialProps: { enabled: false } },
    );

    mousedownOn(document.body);
    expect(onOutside).not.toHaveBeenCalled();

    rerender({ enabled: true });
    mousedownOn(document.body);
    expect(onOutside).toHaveBeenCalledTimes(1);
  });

  it("woła NAJŚWIEŻSZY callback, nie ten z pierwszego renderu (brak stale closure)", () => {
    const el = mountElement();
    const ref = { current: el as HTMLDivElement | null };
    const first = vi.fn();
    const second = vi.fn();

    const { rerender } = renderHook(
      ({ cb }: { cb: () => void }) => useClickOutside(ref, cb),
      { initialProps: { cb: first } },
    );

    rerender({ cb: second });
    mousedownOn(document.body);

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("odpina listener po odmontowaniu", () => {
    const el = mountElement();
    const ref = { current: el as HTMLDivElement | null };
    const onOutside = vi.fn();

    const { unmount } = renderHook(() => useClickOutside(ref, onOutside));
    unmount();
    mousedownOn(document.body);

    expect(onOutside).not.toHaveBeenCalled();
  });

  it("nie wywraca się, gdy ref jest pusty", () => {
    const ref = { current: null as HTMLDivElement | null };
    const onOutside = vi.fn();

    renderHook(() => useClickOutside(ref, onOutside));

    expect(() => mousedownOn(document.body)).not.toThrow();
    expect(onOutside).not.toHaveBeenCalled();
  });
});

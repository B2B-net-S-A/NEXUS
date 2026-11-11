import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { type PickedJob, TwinPickBarView, twinPickHint, useTwinPick } from "../TwinPickBar";

const job = (id: number, ref: string): PickedJob => ({ id, ref, title: `Analityk ${ref}` });

describe("Bliźniaki zaznaczane na liście (11.11.2026)", () => {
  it("toggles picked requests in the order they were clicked", () => {
    const { result } = renderHook(() => useTwinPick());
    act(() => result.current.toggle(job(1, "42933")));
    act(() => result.current.toggle(job(2, "43134")));
    expect(result.current.picked.map((j) => j.ref)).toEqual(["42933", "43134"]);
    expect(result.current.isPicked(2)).toBe(true);
    act(() => result.current.toggle(job(1, "42933")));
    expect(result.current.picked.map((j) => j.ref)).toEqual(["43134"]);
    act(() => result.current.clear());
    expect(result.current.picked).toEqual([]);
  });

  it("says why linking is not possible yet or any more", () => {
    expect(twinPickHint(1)).toBe("Zaznacz jeszcze jedną rekrutację");
    expect(twinPickHint(2)).toBeNull();
    expect(twinPickHint(4)).toBeNull();
    expect(twinPickHint(5)).toMatch(/Najwyżej 4 naraz/);
  });

  it("shows no bar without a selection", () => {
    const { container } = render(
      <TwinPickBarView picked={[]} onRemove={vi.fn()} onClear={vi.fn()} onLink={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("blocks linking a single request and links two, the first marked as first", () => {
    const onLink = vi.fn();
    const onRemove = vi.fn();
    const { rerender } = render(
      <TwinPickBarView picked={[job(1, "42933")]} onRemove={onRemove} onClear={vi.fn()} onLink={onLink} />,
    );
    expect(screen.getByRole("button", { name: /Połącz jako bliźniaki/ })).toBeDisabled();
    rerender(
      <TwinPickBarView
        picked={[job(1, "42933"), job(2, "43134")]}
        onRemove={onRemove}
        onClear={vi.fn()}
        onLink={onLink}
      />,
    );
    expect(screen.getByTestId("twin-pick-bar")).toHaveTextContent("42933pierwsza");
    fireEvent.click(screen.getByRole("button", { name: /Połącz jako bliźniaki/ }));
    expect(onLink).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Odznacz 43134" }));
    expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });
});

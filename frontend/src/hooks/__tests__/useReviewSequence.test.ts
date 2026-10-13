import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useReviewSequence } from "@/hooks/useReviewSequence";

interface Row {
  id: number;
  name: string;
}

const idOf = (row: Row) => row.id;
const rows = (...ids: number[]): Row[] => ids.map((id) => ({ id, name: `Osoba ${id}` }));

describe("useReviewSequence — przegląd po kolei", () => {
  it("przed startem nie ma kolejki", () => {
    const { result } = renderHook(() => useReviewSequence(rows(1, 2), idOf));
    expect(result.current.active).toBe(false);
    expect(result.current.current).toBeNull();
    expect(result.current.total).toBe(0);
  });

  it("idzie po migawce w kolejności startu i liczy pozycję", () => {
    const live = rows(1, 2, 3);
    const { result } = renderHook(() => useReviewSequence(live, idOf));
    act(() => result.current.start(live));
    expect(result.current.current?.id).toBe(1);
    expect(result.current.position).toBe(1);
    expect(result.current.total).toBe(3);
    act(() => result.current.advance());
    expect(result.current.current?.id).toBe(2);
    expect(result.current.position).toBe(2);
    act(() => result.current.advance());
    act(() => result.current.advance());
    // Wszyscy załatwieni: kolejka trwa, ale nie ma kogo pokazać — wołający kończy.
    expect(result.current.active).toBe(true);
    expect(result.current.current).toBeNull();
    act(() => result.current.finish());
    expect(result.current.active).toBe(false);
  });

  it("start od wskazanej osoby — wcześniejsze idą na koniec, nie przepadają", () => {
    const live = rows(1, 2, 3);
    const { result } = renderHook(() => useReviewSequence(live, idOf));
    act(() => result.current.start(live, 2));
    expect(result.current.current?.id).toBe(2);
    act(() => result.current.advance());
    expect(result.current.current?.id).toBe(3);
    act(() => result.current.advance());
    expect(result.current.current?.id).toBe(1);
    expect(result.current.position).toBe(3);
  });

  it("lista odświeżona po decyzji nie zmienia kolejności ani licznika", () => {
    let live = rows(1, 2, 3);
    const { result, rerender } = renderHook(() => useReviewSequence(live, idOf));
    act(() => result.current.start(live));
    act(() => result.current.advance());
    // Serwer oddaje już listę bez osoby 1 (wysłana) — dalej „2 z 3”.
    live = rows(2, 3);
    rerender();
    expect(result.current.current?.id).toBe(2);
    expect(result.current.position).toBe(2);
    expect(result.current.total).toBe(3);
  });

  it("osoba, która zniknęła z listy, jest pomijana", () => {
    let live = rows(1, 2, 3);
    const { result, rerender } = renderHook(() => useReviewSequence(live, idOf));
    act(() => result.current.start(live));
    // Ktoś inny wysłał osobę 2, zanim do niej doszliśmy.
    live = rows(1, 3);
    rerender();
    act(() => result.current.advance());
    expect(result.current.current?.id).toBe(3);
  });

  it("„Pomiń” idzie dalej jak decyzja, ale liczy pominiętych — oni dalej czekają", () => {
    const live = rows(1, 2, 3);
    const { result } = renderHook(() => useReviewSequence(live, idOf));
    act(() => result.current.start(live));
    act(() => result.current.skip());
    expect(result.current.current?.id).toBe(2);
    expect(result.current.skipped).toBe(1);
    act(() => result.current.advance());
    act(() => result.current.skip());
    expect(result.current.current).toBeNull();
    expect(result.current.skipped).toBe(2);
    // Nowa kolejka zaczyna licznik od zera.
    act(() => result.current.start(live));
    expect(result.current.skipped).toBe(0);
  });

  it("dane bieżącej osoby pochodzą z żywej listy", () => {
    let live = rows(1, 2);
    const { result, rerender } = renderHook(() => useReviewSequence(live, idOf));
    act(() => result.current.start(live));
    live = [{ id: 1, name: "Po odświeżeniu" }, { id: 2, name: "Osoba 2" }];
    rerender();
    expect(result.current.current?.name).toBe("Po odświeżeniu");
  });
});

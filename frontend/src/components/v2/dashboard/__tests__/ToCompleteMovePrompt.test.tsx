import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToCompleteMovePrompt } from "../ToCompleteMovePrompt";

// 14.11.2026: przy 390 px tekst stał po jednym słowie w linii, a przyciski
// nachodziły na niego — akapit miał `flex-1` (podstawa 0), więc wiersz z
// `flex-wrap` nigdy się nie zawijał. jsdom nie liczy układu, dlatego test
// pilnuje klas, od których zawijanie zależy.
describe("ToCompleteMovePrompt", () => {
  it("tekst ma niezerową podstawę, a przyciski stoją razem i mogą spaść pod tekst", () => {
    render(<ToCompleteMovePrompt onMove={() => {}} onKeep={() => {}} />);
    const text = screen.getByTestId("to-complete-move-text");
    expect(text.className).not.toMatch(/(^|\s)flex-1(\s|$)/);
    expect(text.className).toContain("flex-[1_1_16rem]");
    expect(text.className).toContain("min-w-0");

    const move = screen.getByRole("button", { name: "Przenieś na pulpit" });
    const keep = screen.getByRole("button", { name: "Zostaw tutaj" });
    expect(move.parentElement).toBe(keep.parentElement);
    expect(move.parentElement).not.toBe(text.parentElement);
    expect(move.parentElement?.className).toContain("shrink-0");
    expect(screen.getByRole("group", { name: "Do uzupełnienia" }).className).toContain("flex-wrap");
  });

  it("przyciski wołają swoje funkcje, a „Przenieś” jest wyłączony w trakcie zapisu", async () => {
    const onMove = vi.fn();
    const onKeep = vi.fn();
    const { rerender } = render(<ToCompleteMovePrompt onMove={onMove} onKeep={onKeep} />);
    await userEvent.click(screen.getByRole("button", { name: "Przenieś na pulpit" }));
    await userEvent.click(screen.getByRole("button", { name: "Zostaw tutaj" }));
    expect(onMove).toHaveBeenCalledTimes(1);
    expect(onKeep).toHaveBeenCalledTimes(1);

    rerender(<ToCompleteMovePrompt onMove={onMove} onKeep={onKeep} busy />);
    expect(screen.getByRole("button", { name: "Przenieś na pulpit" })).toBeDisabled();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JarvisMascot } from "../JarvisMascot";
import { shouldShowMascot } from "../useJarvisMascotVisibility";

describe("Robot Jarvisa — schowaj (zgłoszenie 28.10.2026)", () => {
  it("schowany robot nie wraca w trybie gry", () => {
    expect(shouldShowMascot(false, true, true)).toBe(false);
    expect(shouldShowMascot(false, false, true)).toBe(false);
  });

  it("tryb gry dalej pokazuje robota bez modelu, gdy nie jest schowany", () => {
    expect(shouldShowMascot(true, false, true)).toBe(true);
    expect(shouldShowMascot(true, true, false)).toBe(true);
    expect(shouldShowMascot(true, false, false)).toBe(false);
  });

  const base = {
    name: "Jarvis",
    character: "robot" as const,
    accent: "primary" as const,
    mood: "idle" as const,
    minimized: false,
    onToggle: () => undefined,
  };

  it("× na robocie chowa go, nie otwierając rozmowy", () => {
    const onHide = vi.fn();
    const onToggle = vi.fn();
    render(<JarvisMascot {...base} open={false} onToggle={onToggle} onHide={onHide} />);
    fireEvent.click(screen.getByRole("button", { name: "Schowaj Jarvis" }));
    expect(onHide).toHaveBeenCalledTimes(1);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("przy otwartej rozmowie × nie ma — robot ją wtedy zamyka", () => {
    render(<JarvisMascot {...base} open onHide={() => undefined} />);
    expect(screen.queryByRole("button", { name: "Schowaj Jarvis" })).toBeNull();
  });
});

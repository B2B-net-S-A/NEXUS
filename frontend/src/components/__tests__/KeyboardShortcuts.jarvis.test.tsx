import { fireEvent, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useKeyboardShortcuts } from "../KeyboardShortcuts";

describe("⌘J należy do Jarvisa (0330)", () => {
  it("samo ⌘J nie otwiera już nowej rekrutacji", () => {
    const onNewJob = vi.fn();
    renderHook(() => useKeyboardShortcuts({ onNewJob, onFocusSearch: vi.fn() }));
    fireEvent.keyDown(document, { key: "j", metaKey: true });
    expect(onNewJob).not.toHaveBeenCalled();
  });

  it("⌘⇧J otwiera nową rekrutację (także gdy przeglądarka poda wielkie „J”)", () => {
    const onNewJob = vi.fn();
    renderHook(() => useKeyboardShortcuts({ onNewJob, onFocusSearch: vi.fn() }));
    fireEvent.keyDown(document, { key: "J", metaKey: true, shiftKey: true });
    fireEvent.keyDown(document, { key: "j", ctrlKey: true, shiftKey: true });
    expect(onNewJob).toHaveBeenCalledTimes(2);
  });

  it("goły klawisz „j” dalej działa poza polami tekstowymi", () => {
    const onNewJob = vi.fn();
    renderHook(() => useKeyboardShortcuts({ onNewJob, onFocusSearch: vi.fn() }));
    fireEvent.keyDown(document, { key: "j" });
    expect(onNewJob).toHaveBeenCalledOnce();
  });
});

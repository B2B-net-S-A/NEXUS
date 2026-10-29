import { describe, expect, it } from "vitest";

import { composeKeyAction } from "@/components/v2/pages/chat-compose";

const key = (k: string, mods: Partial<{ shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }> = {}) => ({
  key: k,
  shiftKey: false,
  ctrlKey: false,
  metaKey: false,
  ...mods,
});

describe("composeKeyAction", () => {
  it("zwykłe pole: Enter wysyła, Shift+Enter dodaje linię, Esc anuluje odpowiedź/edycję", () => {
    expect(composeKeyAction(key("Enter"), false)).toBe("send");
    expect(composeKeyAction(key("Enter", { shiftKey: true }), false)).toBeNull();
    expect(composeKeyAction(key("Escape"), false)).toBe("cancel");
    expect(composeKeyAction(key("a"), false)).toBeNull();
  });

  it("rozwinięte pole: Enter dodaje linię, Ctrl/⌘+Enter wysyła, Esc zwija", () => {
    expect(composeKeyAction(key("Enter"), true)).toBeNull();
    expect(composeKeyAction(key("Enter", { shiftKey: true }), true)).toBeNull();
    expect(composeKeyAction(key("Enter", { ctrlKey: true }), true)).toBe("send");
    expect(composeKeyAction(key("Enter", { metaKey: true }), true)).toBe("send");
    expect(composeKeyAction(key("Escape"), true)).toBe("collapse");
  });
});

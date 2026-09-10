/**
 * `copyTextToClipboard` — wynik jest WARTOŚCIĄ, nie domysłem. Wołający
 * pokazuje „skopiowano" wyłącznie przy `true`; przy jednorazowym sekrecie
 * linku fałszywy sukces zostawia żywy link, którego adresu nikt nie zna.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { copyTextToClipboard } from "@/lib/clipboard";

const original = Object.getOwnPropertyDescriptor(globalThis.navigator, "clipboard");

function stubClipboard(value: unknown) {
  Object.defineProperty(globalThis.navigator, "clipboard", {
    value,
    configurable: true,
  });
}

afterEach(() => {
  if (original) {
    Object.defineProperty(globalThis.navigator, "clipboard", original);
  } else {
    // jsdom domyślnie nie ma schowka — przywracamy ten stan.
    stubClipboard(undefined);
  }
});

describe("copyTextToClipboard", () => {
  it("udany zapis → true", async () => {
    const writeText = vi.fn(async () => undefined);
    stubClipboard({ writeText });
    await expect(copyTextToClipboard("https://x/y")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("https://x/y");
  });

  it("odrzucony zapis (np. wygasła aktywacja użytkownika) → false, bez wyjątku", async () => {
    stubClipboard({ writeText: vi.fn(async () => Promise.reject(new Error("NotAllowed"))) });
    await expect(copyTextToClipboard("https://x/y")).resolves.toBe(false);
  });

  it("brak API schowka → false", async () => {
    stubClipboard(undefined);
    await expect(copyTextToClipboard("https://x/y")).resolves.toBe(false);
  });
});

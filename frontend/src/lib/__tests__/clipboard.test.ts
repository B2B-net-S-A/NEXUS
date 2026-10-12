/**
 * `copyTextToClipboard` — wynik jest WARTOŚCIĄ, nie domysłem. Wołający
 * pokazuje „skopiowano" wyłącznie przy `true`; przy jednorazowym sekrecie
 * linku fałszywy sukces zostawia żywy link, którego adresu nikt nie zna.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { copyHtmlToClipboard, copyTextToClipboard } from "@/lib/clipboard";

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

describe("copyHtmlToClipboard", () => {
  const originalItem = (globalThis as { ClipboardItem?: unknown }).ClipboardItem;

  class FakeClipboardItem {
    constructor(public readonly data: Record<string, Blob>) {}
  }

  afterEach(() => {
    (globalThis as { ClipboardItem?: unknown }).ClipboardItem = originalItem;
  });

  it("zapisuje HTML i zwykły tekst w jednym wpisie schowka", async () => {
    (globalThis as { ClipboardItem?: unknown }).ClipboardItem = FakeClipboardItem;
    const write = vi.fn(async (_items: unknown[]) => undefined);
    const writeText = vi.fn(async () => undefined);
    stubClipboard({ write, writeText });

    await expect(copyHtmlToClipboard("<ul><li>a</li></ul>", "a")).resolves.toBe(true);

    const item = write.mock.calls[0][0][0] as FakeClipboardItem;
    expect(Object.keys(item.data)).toEqual(["text/html", "text/plain"]);
    expect(await item.data["text/html"].text()).toBe("<ul><li>a</li></ul>");
    expect(await item.data["text/plain"].text()).toBe("a");
    expect(writeText).not.toHaveBeenCalled();
  });

  it("bez ClipboardItem kopiuje sam tekst", async () => {
    (globalThis as { ClipboardItem?: unknown }).ClipboardItem = undefined;
    const writeText = vi.fn(async () => undefined);
    stubClipboard({ writeText });
    await expect(copyHtmlToClipboard("<p>a</p>", "a")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("a");
  });

  it("odmowa zapisu HTML → zapas tekstowy, a jego odmowa → false", async () => {
    (globalThis as { ClipboardItem?: unknown }).ClipboardItem = FakeClipboardItem;
    const write = vi.fn(async () => Promise.reject(new Error("NotAllowed")));
    const writeText = vi.fn(async () => undefined);
    stubClipboard({ write, writeText });
    await expect(copyHtmlToClipboard("<p>a</p>", "a")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("a");

    stubClipboard({ write, writeText: vi.fn(async () => Promise.reject(new Error("x"))) });
    await expect(copyHtmlToClipboard("<p>a</p>", "a")).resolves.toBe(false);
  });

  it("pusty HTML nie tworzy wpisu z formatowaniem", async () => {
    (globalThis as { ClipboardItem?: unknown }).ClipboardItem = FakeClipboardItem;
    const write = vi.fn(async () => undefined);
    const writeText = vi.fn(async () => undefined);
    stubClipboard({ write, writeText });
    await expect(copyHtmlToClipboard("", "sam tekst")).resolves.toBe(true);
    expect(write).not.toHaveBeenCalled();
    expect(writeText).toHaveBeenCalledWith("sam tekst");
  });
});

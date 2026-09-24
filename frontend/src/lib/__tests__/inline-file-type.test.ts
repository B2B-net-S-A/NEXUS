import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { openContractDocument } from "../contract-documents";
import { inlineSafeType } from "../inline-file-type";
import { openOrderDocument } from "../order-documents";

describe("inlineSafeType", () => {
  it("allows PDF and raster images", () => {
    expect(inlineSafeType("application/pdf")).toBe("application/pdf");
    expect(inlineSafeType("IMAGE/PNG; charset=binary")).toBe("image/png");
  });

  it("refuses anything that can run script from a blob", () => {
    for (const t of ["text/html", "image/svg+xml", "application/xhtml+xml", "text/xml"]) {
      expect(inlineSafeType(t)).toBeNull();
    }
  });

  it("falls back to the response type, and refuses an unknown type", () => {
    expect(inlineSafeType(null, "text/html")).toBeNull();
    expect(inlineSafeType(undefined, "application/pdf")).toBe("application/pdf");
    expect(inlineSafeType(null, "")).toBeNull();
  });
});

describe("opening uploaded documents", () => {
  let tab: { location: { href: string }; close: ReturnType<typeof vi.fn> };
  const blobs: Blob[] = [];

  beforeEach(() => {
    tab = { location: { href: "" }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<script>x</script>", { headers: { "Content-Type": "text/html" } })),
    );
    URL.createObjectURL = vi.fn((b: Blob) => {
      blobs.push(b);
      return "blob:x";
    }) as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    blobs.length = 0;
  });

  it("downloads a contract document declared as text/html instead of opening it", async () => {
    await openContractDocument(1, { id: 2, filename: "umowa.pdf", content_type: "text/html" });
    expect(tab.location.href).toBe("");
    expect(tab.close).toHaveBeenCalled();
    expect(blobs[0].type).toBe("application/octet-stream");
  });

  it("downloads an order document whose response is HTML", async () => {
    await openOrderDocument({ order_id: 3, client_id: 4, filename: "po.pdf", content_type: null });
    expect(tab.location.href).toBe("");
    expect(blobs[0].type).toBe("application/octet-stream");
  });

  it("still opens a real PDF inline", async () => {
    await openContractDocument(1, { id: 2, filename: "umowa.pdf", content_type: "application/pdf" });
    expect(tab.location.href).toBe("blob:x");
    expect(blobs[0].type).toBe("application/pdf");
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import {
  fetchAuthenticatedBlob,
  downloadBlob,
  downloadAuthenticatedFile,
  fetchAuthenticatedObjectUrl,
  openAuthenticatedFile,
} from "@/lib/authenticated-files";

// A minimal Response stand-in — only the bits the helper reads.
function fakeResponse(blob: Blob, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    blob: () => Promise.resolve(blob),
  };
}

describe("authenticated-files", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  const createObjectURL = vi.fn((_blob: Blob) => "blob:mock-url");
  const revokeObjectURL = vi.fn();

  beforeEach(() => {
    localStorage.clear();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // jsdom nie implementuje URL.createObjectURL / revokeObjectURL — podstaw je.
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
    URL.createObjectURL =
      createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL =
      revokeObjectURL as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  describe("fetchAuthenticatedBlob", () => {
    it("attaches the Bearer token from localStorage", async () => {
      localStorage.setItem("access_token", "jwt-123");
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"])));

      await fetchAuthenticatedBlob("/api/emails/1/attachments/2/download");

      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/api/emails/1/attachments/2/download",
        { headers: { Authorization: "Bearer jwt-123" } },
      );
    });

    it("attaches the impersonated user marker to native file requests", async () => {
      localStorage.setItem("access_token", "jwt-admin");
      localStorage.setItem("nexus_impersonate_id", "42");
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"])));

      await fetchAuthenticatedBlob("/api/contracts/7/documents/8/download");

      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/api/contracts/7/documents/8/download",
        {
          headers: {
            Authorization: "Bearer jwt-admin",
            "X-Impersonate-User-Id": "42",
          },
        },
      );
    });

    it("sends no Authorization header when there is no token", async () => {
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"])));

      await fetchAuthenticatedBlob("/api/x");

      expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/x", {
        headers: {},
      });
    });

    it("passes an absolute URL through unchanged", async () => {
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"])));

      await fetchAuthenticatedBlob("https://cdn.example.com/file.pdf");

      expect(fetchMock).toHaveBeenCalledWith(
        "https://cdn.example.com/file.pdf",
        { headers: {} },
      );
    });

    it("throws on a non-ok response (e.g. 401)", async () => {
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"]), 401));

      await expect(fetchAuthenticatedBlob("/api/x")).rejects.toThrow("HTTP 401");
    });

    it("returns the response blob on success", async () => {
      const blob = new Blob(["hello"], { type: "text/plain" });
      fetchMock.mockResolvedValue(fakeResponse(blob));

      await expect(fetchAuthenticatedBlob("/api/x")).resolves.toBe(blob);
    });
  });

  describe("fetchAuthenticatedObjectUrl", () => {
    it("re-types the blob with the given contentType before creating the URL", async () => {
      const raw = new Blob(["%PDF"], { type: "application/octet-stream" });
      fetchMock.mockResolvedValue(fakeResponse(raw));

      const url = await fetchAuthenticatedObjectUrl("/api/x", "application/pdf");

      expect(url).toBe("blob:mock-url");
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      const passed = createObjectURL.mock.calls[0][0];
      expect(passed.type).toBe("application/pdf");
    });

    it("uses the raw blob when no contentType is given", async () => {
      const raw = new Blob(["x"], { type: "image/png" });
      fetchMock.mockResolvedValue(fakeResponse(raw));

      await fetchAuthenticatedObjectUrl("/api/x");

      expect(createObjectURL.mock.calls[0][0]).toBe(raw);
    });
  });

  describe("downloadBlob", () => {
    it("creates an anchor with the download filename, clicks it, and revokes the URL", () => {
      const clickSpy = vi
        .spyOn(HTMLAnchorElement.prototype, "click")
        .mockImplementation(() => {});
      const appendSpy = vi.spyOn(document.body, "appendChild");

      downloadBlob(new Blob(["x"]), "file.txt");

      const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
      expect(anchor.download).toBe("file.txt");
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    });
  });

  describe("downloadAuthenticatedFile", () => {
    it("fetches with auth then triggers the download", async () => {
      localStorage.setItem("access_token", "jwt");
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"])));
      const clickSpy = vi
        .spyOn(HTMLAnchorElement.prototype, "click")
        .mockImplementation(() => {});
      const appendSpy = vi.spyOn(document.body, "appendChild");

      await downloadAuthenticatedFile(
        "/api/emails/1/attachments/2/download",
        "cv.pdf",
      );

      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/api/emails/1/attachments/2/download",
        { headers: { Authorization: "Bearer jwt" } },
      );
      const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
      expect(anchor.download).toBe("cv.pdf");
      expect(clickSpy).toHaveBeenCalledTimes(1);
    });

    it("propagates the error when the fetch fails (caller shows the toast)", async () => {
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"]), 403));

      await expect(
        downloadAuthenticatedFile("/api/x", "f.pdf"),
      ).rejects.toThrow("HTTP 403");
    });
  });

  describe("openAuthenticatedFile", () => {
    it("opens a tab synchronously and points it at the (re-typed) blob URL", async () => {
      const fakeWin = { location: { href: "" }, close: vi.fn() };
      const openSpy = vi
        .spyOn(window, "open")
        .mockReturnValue(fakeWin as unknown as Window);
      fetchMock.mockResolvedValue(
        fakeResponse(new Blob(["<html>"], { type: "application/octet-stream" })),
      );

      await openAuthenticatedFile("/api/x/render-pdf", "text/html");

      expect(openSpy).toHaveBeenCalledWith("", "_blank");
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(createObjectURL.mock.calls[0][0].type).toBe("text/html");
      expect(fakeWin.location.href).toBe("blob:mock-url");
    });

    it("falls back to a download when the popup is blocked", async () => {
      vi.spyOn(window, "open").mockReturnValue(null);
      const clickSpy = vi
        .spyOn(HTMLAnchorElement.prototype, "click")
        .mockImplementation(() => {});
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"])));

      await openAuthenticatedFile("/api/x", "text/html", "fallback.pdf");

      expect(clickSpy).toHaveBeenCalledTimes(1);
    });

    it("closes the opened tab and throws when the fetch fails", async () => {
      const fakeWin = { location: { href: "" }, close: vi.fn() };
      vi.spyOn(window, "open").mockReturnValue(fakeWin as unknown as Window);
      fetchMock.mockResolvedValue(fakeResponse(new Blob(["x"]), 403));

      await expect(openAuthenticatedFile("/api/x")).rejects.toThrow("HTTP 403");
      expect(fakeWin.close).toHaveBeenCalledTimes(1);
    });
  });
});

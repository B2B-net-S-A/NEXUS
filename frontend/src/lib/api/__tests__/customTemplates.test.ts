import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ api: { post: (...a: unknown[]) => post(...a) } }));

import { customTemplatesApi } from "@/lib/api/customTemplates";

describe("customTemplatesApi — formularze z plikiem", () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({ data: { id: 1 } });
  });

  // Staging 25.11.2026: klient `api` wysyłał FormData jako JSON → 422 z serwera.
  it("sends a new template as multipart form data", async () => {
    const file = new File(["x"], "wzor.docx");
    await customTemplatesApi.create({ origin: "upload", name: "Wzór", file, instruction: "zmień" });
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe("/api/b2b-generator/custom-templates");
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("origin")).toBe("upload");
    expect((body as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
  });

  it("uploads a replacement Word file as multipart form data", async () => {
    await customTemplatesApi.upload(7, new File(["x"], "v2.docx"));
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe("/api/b2b-generator/custom-templates/7/upload");
    expect(body).toBeInstanceOf(FormData);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
  });
});

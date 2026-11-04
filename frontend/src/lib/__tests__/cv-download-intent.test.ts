import { expect, it } from "vitest";

import { withDownloadIntent } from "../cv-download-intent";

it("dokleja intencję pobrania i miejsce w aplikacji", () => {
  expect(withDownloadIntent("/api/candidates/stages/21/cv/branded/preview-docx", "editor")).toBe(
    "/api/candidates/stages/21/cv/branded/preview-docx?intent=download&surface=editor",
  );
});

it("nie psuje adresu, który ma już parametry", () => {
  expect(withDownloadIntent("/api/cv-generator/generated/7/docx?v=2", "result")).toBe(
    "/api/cv-generator/generated/7/docx?v=2&intent=download&surface=result",
  );
});

import { describe, expect, it } from "vitest";

import {
  CLOSE_REASON_GROUPS,
  closeReasonGroup,
  closeReasonLabel,
  isSelectableCloseReason,
} from "@/lib/job-close-reasons";

describe("powód nadawany przez NEXUS (28.10.2026)", () => {
  it("„28 dni bez ruchu” to przegrana, ale nie ma go w oknie zamykania", () => {
    expect(closeReasonGroup("no_activity")).toBe("lost");
    expect(closeReasonLabel("no_activity")).toBe("28 dni bez ruchu — zamknął NEXUS");
    expect(isSelectableCloseReason("no_activity")).toBe(false);
    const offered = CLOSE_REASON_GROUPS.flatMap((g) => g.reasons.map((r) => r.value));
    expect(offered).not.toContain("no_activity");
    expect(isSelectableCloseReason("competitor")).toBe(true);
  });
});

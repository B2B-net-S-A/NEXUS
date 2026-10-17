import { describe, expect, it } from "vitest";

import { hitRatioTone } from "../client-hit-ratio";

describe("hitRatioTone — pigułka hit ratio na profilu klienta", () => {
  it("klient na celu jest zielony, nie bursztynowy (audyt N8)", () => {
    expect(hitRatioTone(30, 30)).toBe("bg-success-muted text-success-muted-foreground");
    expect(hitRatioTone(45, 30)).toBe("bg-success-muted text-success-muted-foreground");
  });

  it("od połowy celu do celu — ostrzeżenie", () => {
    expect(hitRatioTone(15, 30)).toBe("bg-warning-muted text-warning-muted-foreground");
    expect(hitRatioTone(29.9, 30)).toBe("bg-warning-muted text-warning-muted-foreground");
  });

  it("poniżej połowy celu — czerwony", () => {
    expect(hitRatioTone(14.9, 30)).toBe("bg-destructive-muted text-destructive-muted-foreground");
    expect(hitRatioTone(0, 30)).toBe("bg-destructive-muted text-destructive-muted-foreground");
  });
});

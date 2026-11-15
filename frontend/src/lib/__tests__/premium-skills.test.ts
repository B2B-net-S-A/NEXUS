import { describe, expect, it } from "vitest";

import type { PremiumClaim } from "@/lib/api/framework-rates";
import { lastRefusal, openClaimFor, proposalLabel } from "@/lib/premium-skills";

const claim = (id: number, technology: string, status: PremiumClaim["status"]): PremiumClaim => ({
  id, technology, status, knows: true, uses: true, dl_note: null, client_confirmed_by: null, client_confirmed_on: null,
  outcome_reason: status === "refused" ? "nice to have" : null, next_try_on: null, created_at: "", updated_at: "",
});

describe("technologie premium", () => {
  it("znajduje otwarty wniosek i ostatnią odmowę bez względu na wielkość liter", () => {
    const claims = [claim(3, "Kafka", "sent"), claim(2, "kafka", "refused"), claim(1, "PEGA", "granted")];
    expect(openClaimFor(claims, "KAFKA")?.id).toBe(3);
    expect(openClaimFor(claims, "PEGA")).toBeNull();
    expect(lastRefusal(claims, "Kafka")?.outcome_reason).toBe("nice to have");
  });

  it("opisuje propozycję NEXUSA", () => {
    expect(proposalLabel({ technology: "Kafka", percent: "20", knows: true, uses: true, sources: [] })).toBe("zna i korzysta");
    expect(proposalLabel({ technology: "Kafka", percent: "20", knows: true, uses: false, sources: [] })).toBe("zna, brak dowodu użycia");
  });
});

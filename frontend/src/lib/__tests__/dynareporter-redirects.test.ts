import { describe, expect, it } from "vitest";

import nextConfig from "../../../next.config";

type Redirect = { source: string; destination: string; permanent: boolean };

async function redirects(): Promise<Redirect[]> {
  return (await nextConfig.redirects?.()) as Redirect[];
}

describe("przekierowania /dynareporter/* (UAT M10-B03)", () => {
  it("clients-mrr ląduje w Radzie, w sekcji Klienci (MRR)", async () => {
    const rule = (await redirects()).find(
      (r) => r.source === "/dynareporter/clients-mrr",
    );
    expect(rule?.destination).toBe("/insights?tab=rada#klienci");
  });

  it("żadne przekierowanie nie celuje w stary alias zakładki", async () => {
    for (const r of await redirects()) {
      expect(r.destination).not.toMatch(/tab=(klienci|zarzad)\b/);
    }
  });
});

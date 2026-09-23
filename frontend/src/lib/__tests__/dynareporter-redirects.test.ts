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
      expect(r.destination).not.toMatch(
        /tab=(klienci|zarzad|rekrutacja|delivery-lead)\b/,
      );
    }
  });

  it("stare raporty Delivery Leada lądują w rozdziale Klienci", async () => {
    const rule = (await redirects()).find(
      (r) => r.source === "/dynareporter/delivery-lead",
    );
    expect(rule?.destination).toBe("/insights?tab=body-leasing&ch=klienci");
  });

  it("Liga Mistrzów ląduje w rozdziale Rywalizacja", async () => {
    const rule = (await redirects()).find(
      (r) => r.source === "/dynareporter/competitions",
    );
    expect(rule?.destination).toBe(
      "/insights?tab=body-leasing&ch=rywalizacja",
    );
  });
});

describe("przekierowanie usuniętej kolejki weryfikacji (17.09.2026)", () => {
  it("stare powiadomienia /pending-verifications nie kończą się 404", async () => {
    const rule = (await redirects()).find((r) => r.source === "/pending-verifications");
    expect(rule).toMatchObject({ destination: "/jobs", permanent: true });
  });
});

describe("usunięte moduły (23.09.2026)", () => {
  it("archiwum admina DynaReportera i MINDY przekierowują trwale", async () => {
    const all = await redirects();
    for (const source of ["/dynareporter", "/dynareporter/:path*", "/dynareporter/mindy"]) {
      expect(all.find((r) => r.source === source)).toMatchObject({ permanent: true });
    }
  });

  it("przekierowanie zbiorcze stoi PO konkretnych — inaczej połknęłoby raporty", async () => {
    const sources = (await redirects()).map((r) => r.source);
    expect(sources.indexOf("/dynareporter/:path*")).toBeGreaterThan(
      sources.indexOf("/dynareporter/clients-mrr"),
    );
  });

  it("Cortex prowadzi na Insights", async () => {
    const rule = (await redirects()).find((r) => r.source === "/cortex");
    expect(rule).toMatchObject({ destination: "/insights", permanent: true });
  });
});

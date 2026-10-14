import { describe, expect, it } from "vitest";

import { portalAdHref } from "@/lib/api/jobAd";

describe("portalAdHref", () => {
  it("przepuszcza adres ogłoszenia na portalu", () => {
    expect(portalAdHref("pracuj", "https://www.pracuj.pl/praca/x,oferta,1")).toBe(
      "https://www.pracuj.pl/praca/x,oferta,1",
    );
    expect(portalAdHref("jjit", "https://justjoin.it/job-offer/x")).toBe(
      "https://justjoin.it/job-offer/x",
    );
    // RocketJobs połączył się z JustJoin.IT — ogłoszenie wisi też pod rocketjobs.pl.
    expect(portalAdHref("jjit", "https://rocketjobs.pl/job-offer/x")).toBe(
      "https://rocketjobs.pl/job-offer/x",
    );
  });

  it.each([
    ["pracuj", "https://obca.example\\.pracuj.pl/oferta"],
    ["pracuj", "https://pracuj.pl.obca.example/oferta"],
    ["pracuj", "https://justjoin.it/job-offer/x"],
    ["pracuj", "https://rocketjobs.pl/job-offer/x"],
    ["jjit", "https://rocketjobs.pl.obca.example/x"],
    ["jjit", "https://zlyrocketjobs.pl/x"],
    ["jjit", "https://obca.example\\@justjoin.it/x"],
    ["jjit", "javascript:alert(1)"],
    ["jjit", "data:text/html,x"],
    ["jjit", "justjoin.it/job-offer/x"],
    ["jjit", ""],
    ["jjit", null],
  ] as const)("%s: %s nie jest odnośnikiem", (portal, url) => {
    expect(portalAdHref(portal, url)).toBeNull();
  });
});

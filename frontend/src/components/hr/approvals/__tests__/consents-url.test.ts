import { describe, expect, it } from "vitest";

import { consentsRedirectHref, myConsentsHref } from "../consents-url";

describe("adres „Zgód i wydatków” w „Moim czasie” (22.10.2026)", () => {
  it("zakładka, zgoda i otwarty formularz", () => {
    expect(myConsentsHref()).toBe("/my-time?tab=consents");
    expect(myConsentsHref({ request: 12 })).toBe("/my-time?tab=consents&request=12");
    expect(myConsentsHref({ isNew: true })).toBe("/my-time?tab=consents&new=1");
  });

  it("stary `/people/consents` przenosi `request` i `new`, resztę odrzuca", () => {
    expect(consentsRedirectHref("")).toBe("/my-time?tab=consents");
    expect(consentsRedirectHref("?request=4")).toBe("/my-time?tab=consents&request=4");
    expect(consentsRedirectHref("request=4&decide=approve")).toBe(
      "/my-time?tab=consents&request=4",
    );
    expect(consentsRedirectHref("new=1")).toBe("/my-time?tab=consents&new=1");
    expect(consentsRedirectHref("request=abc&new=0")).toBe("/my-time?tab=consents");
    expect(consentsRedirectHref("request=-3")).toBe("/my-time?tab=consents");
  });
});

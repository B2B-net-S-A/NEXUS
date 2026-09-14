import { describe, expect, it } from "vitest";

import {
  DEFAULT_FILTERS,
  decodeCompareBackHref,
  decodeFilters,
  decodeSelectedIds,
  encodeCompareHref,
} from "@/lib/url-filters";

const sp = (qs: string) => new URLSearchParams(qs);

describe("url-filters — powrót z porównania (UAT B21)", () => {
  it("link do porównania niesie kontekst listy obok ids", () => {
    const href = encodeCompareHref(
      { ...DEFAULT_FILTERS, q: "QA-E2E", page: 3 },
      [11, 22, 33],
    );
    const [path, qs] = href.split("?");
    expect(path).toBe("/candidates/compare");
    const params = sp(qs);
    expect(params.get("ids")).toBe("11,22,33");
    expect(params.get("q")).toBe("QA-E2E");
    expect(params.get("page")).toBe("3");
  });

  it("link powrotny oddaje filtry, stronę i zaznaczenie", () => {
    const href = encodeCompareHref({ ...DEFAULT_FILTERS, q: "QA-E2E", page: 3 }, [11, 22]);
    const back = decodeCompareBackHref(sp(href.split("?")[1]));
    const [path, qs] = back.split("?");
    expect(path).toBe("/candidates");
    const params = sp(qs);
    expect(params.get("ids")).toBeNull();
    expect(params.get("sel")).toBe("11,22");
    // Lista odtwarza z tego dokładnie te same filtry.
    expect(decodeFilters(params)).toEqual({ ...DEFAULT_FILTERS, q: "QA-E2E", page: 3 });
    expect(decodeSelectedIds(params)).toEqual([11, 22]);
  });

  it("stary link bez kontekstu prowadzi na gołą listę z zaznaczeniem", () => {
    expect(decodeCompareBackHref(sp("ids=5,6"))).toBe("/candidates?sel=5%2C6");
    expect(decodeCompareBackHref(sp(""))).toBe("/candidates");
  });

  it("zaznaczenie odrzuca śmieci i duplikaty", () => {
    expect(decodeSelectedIds(sp("sel=3,abc,-1,3,0,7"))).toEqual([3, 7]);
    expect(decodeSelectedIds(sp(""))).toEqual([]);
  });
});

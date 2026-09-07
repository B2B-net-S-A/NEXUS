import { describe, expect, it } from "vitest";

import { jobsMissingRequestOwner } from "@/lib/jobs-quick-filters";

describe("jobsMissingRequestOwner", () => {
  it("zwraca tylko rekrutacje z `tac_id` = null", () => {
    const jobs = [
      { id: 1, tac_id: 7 },
      { id: 2, tac_id: null },
      { id: 3, tac_id: 9 },
    ];
    expect(jobsMissingRequestOwner(jobs).map((j) => j.id)).toEqual([2]);
  });

  it("traktuje `tac_id` niezdefiniowane tak samo jak null", () => {
    const jobs = [{ id: 1 }, { id: 2, tac_id: 5 }];
    expect(jobsMissingRequestOwner(jobs).map((j) => j.id)).toEqual([1]);
  });

  it("pusta lista → pusty wynik", () => {
    expect(jobsMissingRequestOwner([])).toEqual([]);
  });

  it("wszystkie mają ownera → pusty wynik", () => {
    expect(
      jobsMissingRequestOwner([
        { id: 1, tac_id: 1 },
        { id: 2, tac_id: 2 },
      ]),
    ).toEqual([]);
  });
});

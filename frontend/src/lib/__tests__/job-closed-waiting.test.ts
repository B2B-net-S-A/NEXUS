import { describe, expect, it } from "vitest";

import { cardPersonId, closedOnLabel, myWaitingItems } from "@/lib/job-closed-waiting";

const col = (stage: string, items: object[], extra: object = {}) => ({ stage, items, ...extra }) as never;

describe("myWaitingItems — osoby patrzącego w zamkniętej rekrutacji (28.10.2026)", () => {
  const columns = [
    col("new", [{ candidate_id: 1, added_to_job_by_id: 7 }]),
    col("verified", [{ candidate_id: 2, verified_by_id: 7 }]),
    // „QC CV” po nazwie etapu — jeszcze nie u klienta.
    col("interview", [{ candidate_id: 3, verified_by_id: 7 }], { name: "QC CV" }),
    col("cv_sent", [
      { candidate_id: 4, verified_by_id: 7, added_to_job_by_id: 2 },
      { candidate_id: 5, verified_by_id: 2, added_to_job_by_id: 7 },
      { candidate_id: 6, owner_user_id: 7, verified_by_id: 2 },
    ]),
    col("client_interview", [{ candidate_id: 8, added_to_job_by_id: 7 }]),
    col("negotiation", [{ candidate_id: 9, verified_by_id: 7 }]),
    col("hired", [{ candidate_id: 10, verified_by_id: 7 }]),
    col("rejected", [{ candidate_id: 11, verified_by_id: 7 }], { category: "terminal" }),
  ];

  it("bierze tylko „CV wysłane”, „Rozmowę u klienta” i „Umowę”, z osobą karty jak serwer", () => {
    expect(myWaitingItems(columns, 7).map((i) => i.candidate_id)).toEqual([4, 6, 8, 9]);
  });

  it("bez zalogowanej osoby nic", () => {
    expect(myWaitingItems(columns, null)).toEqual([]);
  });

  it("osoba karty: przypisana, potem weryfikujący, potem dodający", () => {
    expect(cardPersonId({ candidate_id: 1, owner_user_id: 3, verified_by_id: 4, added_to_job_by_id: 5 })).toBe(3);
    expect(cardPersonId({ candidate_id: 1, verified_by_id: 4, added_to_job_by_id: 5 })).toBe(4);
    expect(cardPersonId({ candidate_id: 1, added_to_job_by_id: 5 })).toBe(5);
    expect(cardPersonId({ candidate_id: 1 })).toBeNull();
  });
});

describe("closedOnLabel", () => {
  it("dzień w kalendarzu firmy", () => {
    // 22:30 UTC 19.10 to już 20.10 w Warszawie.
    expect(closedOnLabel("2026-10-19T22:30:00+00:00")).toBe("20.10");
    expect(closedOnLabel(null)).toBeNull();
    expect(closedOnLabel("bzdura")).toBeNull();
  });
});

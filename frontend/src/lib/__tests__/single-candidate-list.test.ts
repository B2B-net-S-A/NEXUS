import { describe, expect, it } from "vitest";

import type { ProposalInboxItem } from "@/lib/job-proposals-api";
import { mergeProposals, type ProposalEntry } from "@/lib/proposals-merge";
import {
  filterOfTab,
  isSingleListTab,
  singleListBadges,
  tabOfFilter,
} from "@/lib/single-candidate-list";

function item(id: number, score: number | null, extra: Partial<ProposalInboxItem> = {}): ProposalInboxItem {
  return {
    candidate: {
      id,
      name: "Osoba",
      lastname: String(id),
      title: null,
      city: null,
      availability_status: null,
      availability_date: null,
      expected_rate_hourly: null,
      expected_rate_redacted: false,
    },
    sources: ["full_base"],
    score,
    evidence: null,
    first_seen_at: null,
    last_seen_at: null,
    is_new: false,
    status: "proposed",
    eligibility: null,
    ...extra,
  };
}

function badges(extra: Partial<ProposalInboxItem>): string[] {
  const [entry] = mergeProposals({ inbox: [item(1, 80, extra)] }) as ProposalEntry[];
  return singleListBadges(entry);
}

describe("jedna lista — filtry i adresy", () => {
  it("dawne zakładki są filtrami, a wyszukiwarki zostają osobno", () => {
    expect(["base", "postings", "similar"].every((t) => isSingleListTab(t as never))).toBe(true);
    expect(isSingleListTab("search")).toBe(false);
    expect(isSingleListTab("manual")).toBe(false);
  });

  it("adres wygrywa z wyborem w panelu tylko dla portali i podobnych", () => {
    expect(filterOfTab("postings", "known")).toBe("portal");
    expect(filterOfTab("similar", "known")).toBe("similar");
    expect(filterOfTab("base", "known")).toBe("known");
  });

  it("filtr wraca na ten sam adres, także po odświeżeniu", () => {
    expect(tabOfFilter("portal")).toBe("postings");
    expect(tabOfFilter("similar")).toBe("similar");
    expect(tabOfFilter("applied")).toBe("base");
    expect(filterOfTab(tabOfFilter("portal"), "all")).toBe("portal");
  });
});

describe("jedna lista — plakietki", () => {
  it("osoba tylko z nocnego przeglądu to „Z bazy”", () => {
    expect(badges({ labels: [] })).toEqual(["Z bazy"]);
  });

  it("portal mówi, skąd osoba jest: portal albo nowe CV", () => {
    expect(badges({ sources: ["job_board"], labels: ["portal"] })).toEqual(["Z portalu"]);
    expect(badges({ sources: ["new_cv"], labels: ["portal"] })).toEqual(["Nowe CV"]);
  });

  it("kilka źródeł to kilka plakietek w stałej kolejności, a „Z bazy” znika", () => {
    expect(
      badges({ sources: ["full_base", "job_board"], labels: ["applied", "portal", "known"] }),
    ).toEqual(["Zgłosił(a) się", "Z portalu", "Znamy"]);
  });

  it("przepięcie ma własną nazwę zamiast „Podobna”", () => {
    expect(badges({ sources: ["reassign"], labels: ["similar"] })).toEqual(["↻ Przepięcie"]);
    expect(badges({ sources: ["similar_projects"], labels: ["similar"] })).toEqual(["Podobna"]);
  });

  it("„Nowy · N dni” rysuje wiersz, więc nie ma drugiej plakietki", () => {
    expect(badges({ labels: ["new_in_base"] })).toEqual(["Z bazy"]);
  });
});

describe("jedna lista — kolejność z serwera", () => {
  it("`keepInboxOrder` nie przestawia skrzynki, a osoby spoza niej idą za nią", () => {
    const entries = mergeProposals({
      inbox: [item(1, 50), item(2, 90)],
      similar: [
        {
          candidate_id: 3,
          name: "Ola",
          lastname: "Hist",
          sources: [],
          same_client: false,
          rejected_by_same_client: false,
        } as never,
      ],
      keepInboxOrder: true,
    });
    expect(entries.map((e) => e.row.candidateId)).toEqual([1, 2, 3]);
  });

  it("bez `keepInboxOrder` kolejność zostaje jak dotąd", () => {
    const entries = mergeProposals({ inbox: [item(1, 50), item(2, 90)] });
    expect(entries.map((e) => e.row.candidateId)).toEqual([2, 1]);
  });

  it("wynik portalu bez skali „Dop.” nie wchodzi do kolumny", () => {
    const [entry] = mergeProposals({
      inbox: [item(1, null, { sources: ["job_board"], board_score: 66, labels: ["portal"] })],
    });
    expect(entry.row.fitScore).toBeNull();
    expect(entry.row.boardScore).toBe(66);
  });
});

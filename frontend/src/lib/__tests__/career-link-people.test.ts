import { describe, expect, it } from "vitest";

import type { LinkPerson } from "@/lib/api/careerLinks";
import { linkPersonLinkName, linkPersonNow } from "@/lib/career-link-people";

const person = (over: Partial<LinkPerson> = {}): LinkPerson => ({
  candidate_id: 1,
  full_name: "Celina Fikcyjna",
  applied_at: "2026-10-28T09:12:00Z",
  was_duplicate: false,
  kind: "job",
  slug: "senior-java-7kq2",
  job_id: 101,
  job_title: "Senior Java Developer",
  current_stage: null,
  current_job_id: null,
  current_job_title: null,
  screening_status: null,
  screening_outcome: null,
  in_my_people: false,
  ...over,
});

describe("linkPersonNow", () => {
  it("etap wygrywa z przeglądem AI; link ogólny mówi, w której rekrutacji", () => {
    expect(
      linkPersonNow(person({ current_stage: "screening", screening_outcome: "added" })),
    ).toBe("Screening");
    expect(
      linkPersonNow(
        person({ kind: "recruiter", current_stage: "new", current_job_title: "Tester" }),
      ),
    ).toBe("Nowy: Tester");
  });

  it("nazywa stan przeglądu AI, gdy karty nie ma", () => {
    expect(linkPersonNow(person({ screening_status: "pending" }))).toBe("Czeka na przegląd AI");
    expect(linkPersonNow(person({ screening_outcome: "screened_out" }))).toBe("Odrzucony przez AI");
    expect(linkPersonNow(person({ screening_outcome: "blocked" }))).toMatch(/Zablokowany/);
  });

  it("bez karty rozróżnia rodzaj linku", () => {
    expect(linkPersonNow(person())).toBe("Bez karty w tej rekrutacji");
    expect(linkPersonNow(person({ kind: "recruiter", job_id: null }))).toBe(
      "W bazie, bez nowej rekrutacji",
    );
    expect(linkPersonNow(person({ screening_outcome: "added" }))).toBe("Bez karty w tej rekrutacji");
  });
});

describe("linkPersonLinkName", () => {
  it("link ogólny i rekrutacja", () => {
    expect(linkPersonLinkName(person({ kind: "recruiter", job_title: null }))).toBe("Mój link ogólny");
    expect(linkPersonLinkName(person())).toBe("Senior Java Developer");
    expect(linkPersonLinkName(person({ job_title: null }))).toBe("Rekrutacja");
  });
});

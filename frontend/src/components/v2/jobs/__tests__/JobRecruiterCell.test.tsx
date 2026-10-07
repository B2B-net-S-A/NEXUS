import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  JobRecruiterCell,
  myCandidatesOutsideTeam,
  type JobListRowFields,
} from "@/components/v2/jobs/JobListCells";
import type { JobRecruiter } from "@/lib/job-team";
import { useAuthStore, type User } from "@/store/auth";

const ME = 7;

function recruiter(user_id: number, extra: Partial<JobRecruiter> = {}): JobRecruiter {
  return {
    user_id,
    name: `Osoba ${user_id}`,
    via: "owner",
    proposed: false,
    assigned_by_name: null,
    ...extra,
  };
}

function job(extra: Partial<JobListRowFields> = {}): JobListRowFields {
  return { recruiters: [recruiter(1)], priority_carry_over_count: 2, ...extra };
}

describe("myCandidatesOutsideTeam", () => {
  it("liczy moich kandydatów w rekrutacji, w której nie jestem Rekruterem", () => {
    expect(myCandidatesOutsideTeam(job(), ME)).toBe(2);
  });

  it("Rekruter rekrutacji plakietki nie dostaje", () => {
    expect(myCandidatesOutsideTeam(job({ recruiters: [recruiter(ME)] }), ME)).toBeNull();
  });

  it("propozycja automatu to jeszcze nie praca — plakietka zostaje", () => {
    expect(
      myCandidatesOutsideTeam(job({ recruiters: [recruiter(ME, { proposed: true })] }), ME),
    ).toBe(2);
  });

  it("bez moich kandydatów albo bez zalogowanej osoby — nic", () => {
    expect(myCandidatesOutsideTeam(job({ priority_carry_over_count: 0 }), ME)).toBeNull();
    expect(myCandidatesOutsideTeam(job({ priority_carry_over_count: null }), ME)).toBeNull();
    expect(myCandidatesOutsideTeam(job(), null)).toBeNull();
  });
});

describe("JobRecruiterCell", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { id: ME } as User });
  });

  it("pokazuje „Twoi kandydaci: N” pod rekruterem", () => {
    render(<JobRecruiterCell job={job({ priority_carry_over_count: 3 })} />);
    const badge = screen.getByTestId("job-my-candidates");
    expect(badge).toHaveTextContent("Twoi kandydaci: 3");
    expect(badge).toHaveAttribute("title", "Prowadzisz tu 3 osoby, choć nie jesteś Rekruterem tej rekrutacji");
  });

  it("nie pokazuje plakietki Rekruterowi rekrutacji", () => {
    render(<JobRecruiterCell job={job({ recruiters: [recruiter(ME)] })} />);
    expect(screen.queryByTestId("job-my-candidates")).not.toBeInTheDocument();
  });
});

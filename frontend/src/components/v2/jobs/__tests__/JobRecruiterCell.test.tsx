import { render, screen, within } from "@testing-library/react";
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

  const team = [
    recruiter(1, { name: "Anna Nowak" }),
    recruiter(2, { name: "Jan Kowalski", via: "assignment" }),
    recruiter(3, { name: "Ewa Zielińska", via: "collaborator" }),
    recruiter(4, { name: "Olga Lis", via: "collaborator" }),
  ];

  it("dwie osoby z nazwiska, reszta za „+N”", () => {
    render(<JobRecruiterCell job={job({ recruiters: team })} />);
    const cell = within(screen.getByTestId("job-recruiter-cell"));
    expect(cell.getByText("Anna N.")).toBeInTheDocument();
    expect(cell.getByText("Jan K.")).toBeInTheDocument();
    expect(cell.queryByText("Ewa Z.")).not.toBeInTheDocument();
    expect(cell.getByText("+2")).toBeInTheDocument();
  });

  it("osoba z filtra „Rekruter” stoi w wierszu z nazwiska, choć jest czwarta", () => {
    render(<JobRecruiterCell job={job({ recruiters: team })} highlightIds={[4]} />);
    const cell = within(screen.getByTestId("job-recruiter-cell"));
    expect(cell.getByText("Olga L.")).toBeInTheDocument();
    expect(cell.getByText("Anna N.")).toBeInTheDocument();
    expect(cell.queryByText("Jan K.")).not.toBeInTheDocument();
    expect(cell.getByText("+2")).toBeInTheDocument();
    // W podpowiedzi nadal wszyscy.
    expect(
      cell.getByTitle("Rekruterzy: Olga Lis, Anna Nowak, Jan Kowalski, Ewa Zielińska"),
    ).toBeInTheDocument();
  });

  it("zalogowany rekruter widzi siebie w wierszu, choć jest trzeci", () => {
    const mine = [team[0], team[1], recruiter(ME, { name: "Marek Testowy", via: "assignment" })];
    render(<JobRecruiterCell job={job({ recruiters: mine })} />);
    const cell = within(screen.getByTestId("job-recruiter-cell"));
    expect(cell.getByText("Marek T.")).toBeInTheDocument();
    expect(cell.getByText("Anna N.")).toBeInTheDocument();
    expect(cell.getByText("+1")).toBeInTheDocument();
  });

  it("osoba z filtra stoi przed zalogowaną", () => {
    const mine = [...team, recruiter(ME, { name: "Marek Testowy", via: "assignment" })];
    render(<JobRecruiterCell job={job({ recruiters: mine })} highlightIds={[3]} />);
    const cell = within(screen.getByTestId("job-recruiter-cell"));
    expect(cell.getByText("Ewa Z.")).toBeInTheDocument();
    expect(cell.getByText("Marek T.")).toBeInTheDocument();
    expect(cell.getByText("+3")).toBeInTheDocument();
  });
});

describe("JobRecruiterCell — „Poprzedni rekruter” (14.10.2026)", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { id: ME } as User });
  });

  const previous = (user_id: number, name: string) => ({
    user_id,
    name,
    via: "owner" as const,
    reason: "priority" as const,
    parked_at: "2026-10-14T13:02:00Z",
    parked_by_name: null,
    will_return: true,
  });

  it("cały zespół wśród poprzednich: szare „poprzedni” zamiast „Bez rekrutera”", () => {
    render(
      <JobRecruiterCell
        job={job({
          recruiters: [],
          previous_recruiters: [previous(3, "Tomasz Lis"), previous(4, "Ewa Mazur")],
        })}
      />,
    );

    const cell = screen.getByTestId("job-previous-recruiter");
    expect(cell).toHaveTextContent("Tomasz L.");
    expect(cell).toHaveTextContent("+1");
    expect(cell).toHaveTextContent("poprzedni");
    expect(cell).toHaveAttribute(
      "title",
      "Poprzedni rekruterzy: Tomasz Lis, Ewa Mazur — wrócą przy P1",
    );
    expect(screen.queryByTestId("job-no-recruiter")).not.toBeInTheDocument();
  });

  it("ktoś pracuje — poprzedni nie zasłaniają rekrutera", () => {
    render(
      <JobRecruiterCell
        job={job({ previous_recruiters: [previous(3, "Tomasz Lis")] })}
      />,
    );

    expect(screen.queryByTestId("job-previous-recruiter")).not.toBeInTheDocument();
    expect(screen.getByTestId("job-recruiter-cell")).toHaveTextContent("Osoba 1");
  });

  it("bez nikogo i bez poprzednich zostaje „Bez rekrutera”", () => {
    render(<JobRecruiterCell job={job({ recruiters: [] })} />);

    expect(screen.getByTestId("job-no-recruiter")).toBeInTheDocument();
  });
});

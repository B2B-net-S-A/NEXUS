import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  JobRecruiterCell,
  jobListPeopleIds,
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

describe("JobRecruiterCell — nieobecni dziś (moduł urlopów)", () => {
  const away = (user_id: number, substitute_name: string | null = "Marta Zastępcza") => ({
    user_id,
    until: "2099-10-23",
    half_day: null,
    substitute_user_id: substitute_name ? 99 : null,
    substitute_name,
  });

  beforeEach(() => {
    useAuthStore.setState({ user: { id: ME } as User });
  });

  it("bez danych o nieobecnościach komórka jest jak dotąd", () => {
    render(
      <JobRecruiterCell
        job={job({ delivery_lead_id: 5, delivery_lead_user: { name: "Kamil Testowy" } })}
      />,
    );
    expect(screen.queryByTestId("job-recruiter-absence")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-delivery-lead-absence")).not.toBeInTheDocument();
  });

  it("nieobecny Rekruter: kropka z tekstem w podpowiedzi, bez rodzaju", () => {
    render(<JobRecruiterCell job={job()} absences={new Map([[1, away(1)]])} />);
    const dot = screen.getByTestId("job-recruiter-absence");
    expect(dot).toHaveAttribute(
      "title",
      "Osoba 1: Nieobecność do 23.10 · zastępuje Marta Z.",
    );
    expect(dot).toHaveTextContent("Osoba 1: Nieobecność do 23.10");
    expect(screen.queryByTestId("job-delivery-lead-absence")).not.toBeInTheDocument();
  });

  it("nieobecny DL: kropka przy „DL: …”, tekst DL bez zmian", () => {
    render(
      <JobRecruiterCell
        job={job({ delivery_lead_id: 5, delivery_lead_user: { name: "Kamil Testowy" } })}
        absences={new Map([[5, away(5, null)]])}
      />,
    );
    expect(screen.getByTestId("job-delivery-lead")).toHaveTextContent("DL: Kamil T.");
    expect(screen.getByTestId("job-delivery-lead-absence")).toHaveAttribute(
      "title",
      "Kamil Testowy: Nieobecność do 23.10",
    );
    expect(screen.queryByTestId("job-recruiter-absence")).not.toBeInTheDocument();
  });

  it("propozycja automatu nie dostaje kropki — to jeszcze nie praca", () => {
    render(
      <JobRecruiterCell
        job={job({ recruiters: [recruiter(1), recruiter(2, { proposed: true })] })}
        absences={new Map([[2, away(2)]])}
      />,
    );
    expect(screen.queryByTestId("job-recruiter-absence")).not.toBeInTheDocument();
  });
});

describe("jobListPeopleIds", () => {
  it("pracujący Rekruterzy i DL z całej strony, bez powtórzeń i propozycji", () => {
    const ids = jobListPeopleIds([
      job({ recruiters: [recruiter(1), recruiter(2, { proposed: true })], delivery_lead_id: 5 }),
      job({ recruiters: [recruiter(1), recruiter(3)], delivery_lead_id: null }),
    ]);
    expect([...ids].sort()).toEqual([1, 3, 5]);
  });
});

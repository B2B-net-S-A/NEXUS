import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { JobApplicantsList, type JobApplicant } from "@/components/v2/jobs/JobApplicantsTile";

const row = (over: Partial<JobApplicant>): JobApplicant => ({
  candidate_id: 1,
  name: "Osoba Test",
  channel: "JustJoin.IT",
  applied_at: "2026-11-05T12:00:00Z",
  stage: "new",
  in_job: true,
  also_fits: [],
  ...over,
});

describe("Aplikacje z ogłoszenia (07.11.2026)", () => {
  it("domyślnie pokazuje osoby w tej rekrutacji, „Wszyscy” — całą listę", async () => {
    render(
      <JobApplicantsList
        items={[
          row({ candidate_id: 1, name: "W Rekrutacji" }),
          row({ candidate_id: 2, name: "Poza Nią", in_job: false, stage: null }),
        ]}
      />,
    );
    expect(screen.getByText("W Rekrutacji")).toBeTruthy();
    expect(screen.queryByText("Poza Nią")).toBeNull();

    await userEvent.click(screen.getByTestId("applicants-filter-all"));

    expect(screen.getByText("Poza Nią")).toBeTruthy();
    expect(screen.getByText("poza rekrutacją")).toBeTruthy();
  });

  it("„Pasuje też do” prowadzi do innej rekrutacji z wynikiem", () => {
    render(
      <JobApplicantsList
        items={[row({ also_fits: [{ job_id: 763073, title: "Full Stack Java", score: 71.4 }] })]}
      />,
    );
    const link = screen.getByTestId("applicant-also-fits");
    expect(link.textContent).toBe("Full Stack Java · 71");
    expect(link.getAttribute("href")).toBe("/jobs/763073");
  });
});

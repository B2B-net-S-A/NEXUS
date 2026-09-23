import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PrepSummary } from "@/components/calendar/cycle/PrepReviewDialog";
import { defaultOrganizerId } from "@/components/calendar/cycle/PlanPrepDialog";
import { prepStatusLine, type Prep } from "@/lib/api/prepMeetings";

function prep(partial: Partial<Prep> = {}): Prep {
  return {
    event_id: 1,
    prep_no: 1,
    candidate_id: 2,
    job_id: 3,
    organizer: { id: 8, name: "Kasia DL" },
    start: "2031-06-10T10:00:00Z",
    end: "2031-06-10T10:45:00Z",
    online_meeting_url: null,
    transcription_setup: "enabled",
    transcript_status: "fetched",
    talk_share: 0.58,
    duration_seconds: 31 * 60,
    review: {
      status: "ok",
      level: "ok",
      coverage: 0.66,
      criteria: {
        items: [
          { key: "must:Kafka", label: "Kafka", kind: "must", status: "covered", quote: "integracje na Kafce" },
          { key: "must:Azure", label: "Azure", kind: "must", status: "missing", quote: null, unverified: true },
          { key: "q:1", label: "Jak skalujesz?", kind: "question", status: "covered_in_prep1", quote: null },
        ],
        own_projects: { told: true, quote: "W banku przez dwa lata" },
      },
      summary: "Dobry prep, brakło Azure.",
      remaining: ["Azure"],
    },
    ...partial,
  };
}

describe("PrepSummary (0355)", () => {
  it("pokazuje ocenę, punkty z cytatem i to, co zostało na Prep 2", () => {
    render(<PrepSummary prep={prep()} />);
    expect(screen.getByText("Ocena: OK")).toBeInTheDocument();
    expect(screen.getByText("„integracje na Kafce”")).toBeInTheDocument();
    expect(screen.getByText("Nie było (bez dowodu)")).toBeInTheDocument();
    expect(screen.getByText("Omówione w Prep 1")).toBeInTheDocument();
    expect(screen.getByText("Na Prep 2 zostało")).toBeInTheDocument();
    expect(screen.getByText(/kandydat mówił 58%/)).toBeInTheDocument();
  });

  it("awaria AI nie udaje oceny — mówi wprost, że jest niedostępna", () => {
    render(
      <PrepSummary
        prep={prep({
          review: { status: "unavailable", level: null, coverage: null, criteria: {}, summary: null, remaining: [] },
        })}
      />,
    );
    expect(screen.queryByText(/Ocena:/)).not.toBeInTheDocument();
    expect(screen.getByText(/Ocena AI jest niedostępna/)).toBeInTheDocument();
  });

  it("prep bez nagrania i czekający na transkrypt mają własne zdanie", () => {
    expect(prepStatusLine(prep({ transcript_status: "missing", review: null }))).toMatch(/nie ma transkryptu/);
    expect(prepStatusLine(prep({ transcript_status: "waiting", review: null }))).toMatch(/Czekamy/);
    expect(prepStatusLine(prep({ transcript_status: "forbidden", review: null }))).toMatch(/nie ma dostępu/);
  });
});

describe("defaultOrganizerId", () => {
  it("bierze podpowiedź serwera dla numeru prepu", () => {
    const suggested = { "1": { id: 8 }, "2": { id: 7 } };
    expect(defaultOrganizerId(suggested, 1)).toBe(8);
    expect(defaultOrganizerId(suggested, 2)).toBe(7);
    expect(defaultOrganizerId({ "1": null }, 1)).toBeNull();
  });
});

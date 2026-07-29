import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import type { CandidateContactCaseStatus } from "@/lib/candidate-contact";

const LABELS: Record<CandidateContactCaseStatus, string> = {
  unassigned: "Nieprzydzielony",
  awaiting_capacity: "Czeka na miejsce",
  queued: "Do przedzwonienia",
  callback_due: "Callback",
  cooldown: "Cooldown",
  handoff_pending: "Po rozmowie",
  blocked_no_phone: "Brak numeru",
  suppressed: "Nie kontaktować",
  completed: "Kontakt zakończony",
  cancelled: "Anulowany",
};

describe("ContactStatusBadge", () => {
  it.each(Object.entries(LABELS))(
    "uses the shared label for %s",
    (status, label) => {
      render(
        <ContactStatusBadge
          contactCase={{
            status: status as CandidateContactCaseStatus,
          }}
        />,
      );

      expect(screen.getByText(label)).toBeInTheDocument();
    },
  );

  it("shows the neutral pre-activation label when no process exists", () => {
    render(<ContactStatusBadge contactCase={null} />);

    expect(
      screen.getByText("Brak danych sprzed uruchomienia"),
    ).toBeInTheDocument();
  });
});

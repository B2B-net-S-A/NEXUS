import * as React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  JobDetailCompactHeader,
  type JobDetailTab,
} from "@/components/v2/jobs/JobDetailCompactHeader";

function renderHeader(
  overrides: Partial<React.ComponentProps<typeof JobDetailCompactHeader>> = {},
) {
  const onTabChange = vi.fn<(tab: JobDetailTab) => void>();
  const onAddCandidate = vi.fn();
  const onEdit = vi.fn();

  render(
    <JobDetailCompactHeader
      title="Senior Java Developer"
      referenceNumber="REF-505734"
      badges={<span>Aktywna</span>}
      metadata={<span>Warszawa</span>}
      activeTab="pipeline"
      onTabChange={onTabChange}
      onAddCandidate={onAddCandidate}
      onEdit={onEdit}
      chatUnreadCount={3}
      contextOpen={false}
      onContextOpenChange={vi.fn()}
      contextContent={<div>Zespół operacyjny</div>}
      {...overrides}
    />,
  );

  return { onTabChange, onAddCandidate, onEdit };
}

describe("JobDetailCompactHeader", () => {
  it("zawsze pokazuje identyfikację, status i główną akcję", async () => {
    const { onAddCandidate } = renderHeader();

    expect(
      screen.getByRole("heading", { name: "Senior Java Developer" }),
    ).toBeTruthy();
    expect(screen.getByText("REF-505734")).toBeTruthy();
    expect(screen.getByText("Aktywna")).toBeTruthy();

    await userEvent.click(
      screen.getByRole("button", { name: "Dodaj kandydata" }),
    );
    expect(onAddCandidate).toHaveBeenCalledOnce();
  });

  it("grupuje pozyskiwanie i narzędzia bez utraty żadnej sekcji", async () => {
    const { onTabChange } = renderHeader();

    expect(screen.getByRole("button", { name: "Pipeline" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Historia" })).toBeTruthy();

    await userEvent.click(
      screen.getByRole("button", { name: "Pozyskaj kandydatów" }),
    );
    expect(
      await screen.findByRole("menuitem", { name: "AI Matching" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("menuitem", { name: "Portale ogłoszeniowe" }),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Wyszukaj manualnie" }),
    );
    expect(onTabChange).toHaveBeenCalledWith("manual-search");

    await userEvent.click(
      screen.getByRole("button", { name: "Narzędzia, 3 nieprzeczytane" }),
    );
    expect(
      await screen.findByRole("menuitem", { name: "Profil Championa" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("menuitem", { name: "Baza pytań" }),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Chat, 3 nieprzeczytane" }),
    );
    expect(onTabChange).toHaveBeenCalledWith("chat");
  });

  it("oznacza aktywną grupę i dokładną pozycję menu", async () => {
    renderHeader({ activeTab: "manual-search" });

    const sourcing = screen.getByRole("button", {
      name: "Pozyskaj kandydatów",
    });
    expect(sourcing).toHaveAttribute("aria-current", "page");
    await userEvent.click(sourcing);
    expect(
      await screen.findByRole("menuitem", { name: "Wyszukaj manualnie" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("zamyka menu przed odroczonym otwarciem modala akcji", async () => {
    const { onEdit } = renderHeader();

    await userEvent.click(
      screen.getByRole("button", { name: "Więcej akcji rekrutacji" }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: "Edytuj" }));

    await waitFor(() => expect(onEdit).toHaveBeenCalledOnce());
    expect(screen.queryByRole("menuitem", { name: "Edytuj" })).toBeNull();
  });

  it("trzyma zespół i Priority Work pod jednym disclosure", async () => {
    function Harness() {
      const [open, setOpen] = React.useState(false);
      return (
        <JobDetailCompactHeader
          title="Senior Java Developer"
          activeTab="pipeline"
          onTabChange={vi.fn()}
          onAddCandidate={vi.fn()}
          contextOpen={open}
          onContextOpenChange={setOpen}
          contextContent={<div>Zespół operacyjny</div>}
        />
      );
    }

    render(<Harness />);
    expect(screen.queryByText("Zespół operacyjny")).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: /Zespół i priorytet/ }),
    );
    expect(await screen.findByText("Zespół operacyjny")).toBeTruthy();
  });
});

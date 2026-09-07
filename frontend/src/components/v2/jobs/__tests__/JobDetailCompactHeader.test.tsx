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

  it("nie pokazuje głównej akcji, gdy sekcja jest tylko do odczytu", () => {
    renderHeader({
      onAddCandidate: undefined,
      onEdit: undefined,
      onWriteAnnouncement: undefined,
      onGenerateInviteLink: undefined,
    });

    expect(
      screen.queryByRole("button", { name: "Dodaj kandydata" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Więcej akcji rekrutacji" }),
    ).toBeNull();
    // Nawigacja po krokach zostaje także w trybie tylko-do-odczytu.
    expect(
      screen.getByRole("button", { name: "Pozyskaj kandydatów" }),
    ).toBeTruthy();
  });

  it("listwa kroków idzie w kolejności procesu i nie gubi żadnej sekcji", async () => {
    const { onTabChange } = renderHeader();

    // Bezpośrednie kroki (bez menu): Zlecenie i Champion · Pipeline · Baza pytań,
    // po prawej Historia i Chat.
    const nav = screen.getByRole("navigation", { name: "Sekcje rekrutacji" });
    const labels = Array.from(nav.querySelectorAll("button")).map((b) =>
      (b.textContent ?? "").replace(/\d+$/, "").trim(),
    );
    expect(labels).toEqual([
      "Zlecenie i Champion",
      "Pozyskiwanie",
      "Pipeline",
      "Baza pytań",
      "Rozmowy i decyzja",
      "Umowa",
    ]);

    await userEvent.click(
      screen.getByRole("button", { name: "Zlecenie i Champion" }),
    );
    expect(onTabChange).toHaveBeenCalledWith("champion");
    await userEvent.click(screen.getByRole("button", { name: "Baza pytań" }));
    expect(onTabChange).toHaveBeenCalledWith("questions");
    await userEvent.click(
      screen.getByRole("button", { name: "Rozmowy i decyzja" }),
    );
    expect(onTabChange).toHaveBeenCalledWith("interviews");
    await userEvent.click(screen.getByRole("button", { name: "Umowa" }));
    expect(onTabChange).toHaveBeenCalledWith("contract");
    await userEvent.click(screen.getByRole("button", { name: "Historia" }));
    expect(onTabChange).toHaveBeenCalledWith("history");
    await userEvent.click(
      screen.getByRole("button", { name: "Chat, 3 nieprzeczytane" }),
    );
    expect(onTabChange).toHaveBeenCalledWith("chat");

    // Pozyskiwanie zostaje menu (AI Matching / manualne / portale), dopóki rama
    // źródeł nie zastąpi trzech osobnych zakładek jedną powierzchnią.
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
  });

  it("nie ma już menu Narzędzia — Champion, Baza pytań i Chat są krokami", () => {
    renderHeader();
    expect(screen.queryByRole("button", { name: /Narzędzia/ })).toBeNull();
    expect(screen.getByTestId("tab-champion")).toBeTruthy();
    expect(screen.getByTestId("tab-questions")).toBeTruthy();
    expect(screen.getByTestId("tab-chat")).toBeTruthy();
    expect(screen.getByTestId("tab-history")).toBeTruthy();
    expect(screen.getByTestId("tab-interviews")).toBeTruthy();
    expect(screen.getByTestId("tab-contract")).toBeTruthy();
  });

  it("liczniki kroków 07 i 08 milczą, dopóki nie ma czego policzyć", () => {
    // `undefined` = kanban jeszcze nie wczytany. Zero w tym miejscu czytałoby
    // się jako „nikt nie jest u klienta", a to inna wiadomość niż „nie wiem".
    renderHeader({ interviewsCount: undefined, contractCount: undefined });
    expect(
      screen.getByRole("button", { name: "Rozmowy i decyzja" }).textContent,
    ).toBe("Rozmowy i decyzja");
    expect(screen.getByRole("button", { name: "Umowa" }).textContent).toBe(
      "Umowa",
    );
  });

  it("policzone zero jest pokazywane — to inna wiadomość niż brak danych", () => {
    renderHeader({ interviewsCount: 2, contractCount: 0 });
    expect(
      screen.getByRole("button", { name: "Rozmowy i decyzja" }).textContent,
    ).toBe("Rozmowy i decyzja2");
    expect(screen.getByRole("button", { name: "Umowa" }).textContent).toBe(
      "Umowa0",
    );
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

  it("pokazuje licznik w procesie na Pipeline tylko, gdy jest policzony", () => {
    const { unmount } = render(
      <JobDetailCompactHeader
        title="Senior Java Developer"
        activeTab="pipeline"
        onTabChange={vi.fn()}
        contextOpen={false}
        onContextOpenChange={vi.fn()}
        contextContent={<div />}
      />,
    );
    expect(screen.getByRole("button", { name: "Pipeline" })).toBeTruthy();
    unmount();

    render(
      <JobDetailCompactHeader
        title="Senior Java Developer"
        activeTab="pipeline"
        onTabChange={vi.fn()}
        pipelineCount={15}
        contextOpen={false}
        onContextOpenChange={vi.fn()}
        contextContent={<div />}
      />,
    );
    const pipeline = screen.getByRole("button", { name: /^Pipeline/ });
    expect(pipeline.textContent).toContain("15");
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

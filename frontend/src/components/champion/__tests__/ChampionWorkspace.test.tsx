/**
 * „Profil Championa” w czterech zakładkach (04.10.2026): przełączanie
 * zakładek, szuflada edycji bloku i przejście braków bramki do właściwego
 * bloku (albo pełnego formularza, gdy blok nie istnieje).
 */
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChampionWorkspace,
  type ChampionWorkspaceProps,
} from "@/components/champion/ChampionWorkspace";
import type { ChampionTab } from "@/lib/champion-blocks";

const plainBriefMock = vi.fn();
vi.mock("@/lib/api/plainKnowledge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/plainKnowledge")>();
  return { ...actual, usePlainBrief: () => plainBriefMock() };
});
vi.mock("@/components/champion/ChampionBriefView", () => ({
  ChampionBriefView: ({
    onEditBlock,
    onOpenTeam,
  }: {
    onEditBlock?: (b: string) => void;
    onOpenTeam?: () => void;
  }) => (
    <div data-testid="brief">
      {onEditBlock ? (
        <button type="button" onClick={() => onEditBlock("search")}>
          edytuj czego szukamy
        </button>
      ) : null}
      <button type="button" onClick={onOpenTeam}>
        zespół
      </button>
    </div>
  ),
}));
vi.mock("@/components/champion/ChampionTodoStrip", () => ({
  ChampionTodoStrip: ({ onGoChampion }: { onGoChampion: (a: string | null) => void }) => (
    <div data-testid="todo">
      <button type="button" onClick={() => onGoChampion("champion-section-screening")}>
        brak pytań
      </button>
      <button type="button" onClick={() => onGoChampion(null)}>
        brak tytułu
      </button>
    </div>
  ),
}));
vi.mock("@/components/champion/ChampionClientTab", () => ({
  ChampionClientTab: () => <div data-testid="client-tab" />,
}));
vi.mock("@/components/champion/plain/PlainBriefBlock", () => ({
  PlainBriefBlock: ({ parts }: { parts?: string }) => <div data-testid="plain" data-parts={parts} />,
}));
vi.mock("@/components/v2/jobs/JobReadinessDock", () => ({
  JobTeamTab: () => <div data-testid="team-tab" />,
}));
vi.mock("@/components/v2/jobs/JobAnnouncementSection", () => ({
  JobAnnouncementSection: ({ portalsFocus, readOnly }: { portalsFocus?: boolean; readOnly: boolean }) => (
    <div data-testid="announce" data-focus={String(!!portalsFocus)} data-read-only={String(readOnly)} />
  ),
}));
vi.mock("@/components/champion/ChampionEditDrawer", () => ({
  ChampionEditDrawer: ({ block }: { block: string | null }) =>
    block ? <div data-testid="drawer" data-block={block} /> : null,
}));

function Harness(props: Partial<ChampionWorkspaceProps> & { initialTab?: ChampionTab }) {
  const [tab, setTab] = useState<ChampionTab>(props.initialTab ?? "brief");
  return (
    <ChampionWorkspace
      jobId={7}
      job={{ client_id: 3, status: "published" }}
      tab={tab}
      onTabChange={setTab}
      canEditChampion
      canWritePipeline
      canSeeGate
      canEditJob
      canEditJobContent
      onEditJob={() => undefined}
      onEditFull={() => undefined}
      {...props}
    />
  );
}

beforeEach(() => {
  plainBriefMock.mockReset();
  plainBriefMock.mockReturnValue({ data: undefined });
});

describe("ChampionWorkspace", () => {
  it("cztery zakładki; Brief domyślnie, przełączanie pokazuje treść zakładki", async () => {
    render(<Harness />);
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Brief", "Technologie po ludzku", "Klient i historia", "Zespół i ogłoszenie"]);
    expect(screen.getByTestId("brief")).toBeInTheDocument();
    expect(screen.getByTestId("todo")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Technologie po ludzku" }));
    expect(screen.getByTestId("plain")).toHaveAttribute("data-parts", "knowledge");
    await userEvent.click(screen.getByRole("tab", { name: "Klient i historia" }));
    expect(screen.getByTestId("client-tab")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Zespół i ogłoszenie" }));
    expect(screen.getByTestId("team-tab")).toBeInTheDocument();
    expect(screen.getByTestId("announce")).toHaveAttribute("data-read-only", "false");
  });

  it("licznik haseł słowniczka przy „Technologie po ludzku”", () => {
    plainBriefMock.mockReturnValue({
      data: {
        glossary: [
          { display_name: "Java", status: "ready", summary: "Język" },
          { display_name: "Kafka", status: "researching", summary: null },
        ],
      },
    });
    render(<Harness />);
    expect(screen.getByRole("tab", { name: /Technologie po ludzku/ })).toHaveTextContent("1");
  });

  it("„Edytuj” w Briefie otwiera szufladę tego bloku", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "edytuj czego szukamy" }));
    expect(screen.getByTestId("drawer")).toHaveAttribute("data-block", "search");
  });

  it("brak z bramki wskazujący sekcję otwiera jej blok; bez bloku — pełny formularz", async () => {
    const onEditFull = vi.fn();
    render(<Harness onEditFull={onEditFull} />);
    await userEvent.click(screen.getByRole("button", { name: "brak pytań" }));
    expect(screen.getByTestId("drawer")).toHaveAttribute("data-block", "screening");
    await userEvent.click(screen.getByRole("button", { name: "brak tytułu" }));
    expect(onEditFull).toHaveBeenCalledWith(null);
  });

  it("bez prawa edycji Championa nie ma szuflady — brak prowadzi do pełnego formularza", async () => {
    const onEditFull = vi.fn();
    render(<Harness canEditChampion={false} onEditFull={onEditFull} />);
    expect(screen.queryByRole("button", { name: "edytuj czego szukamy" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "brak pytań" }));
    expect(screen.queryByTestId("drawer")).toBeNull();
    expect(onEditFull).toHaveBeenCalledWith("champion-section-screening");
  });

  it("„Kto prowadzi → Zespół” przechodzi do zakładki zespołu; stary link portali rozwija portale", async () => {
    render(<Harness portalsFocus />);
    await userEvent.click(screen.getByRole("button", { name: "zespół" }));
    expect(screen.getByTestId("announce")).toHaveAttribute("data-focus", "true");
  });

  it("niezapisany pełny formularz: „Edytuj” przy bloku prowadzi do formularza, nie do szuflady", async () => {
    // Zapis z szuflady odświeża profil i skasowałby szkic ukrytego formularza.
    const onEditFull = vi.fn();
    render(<Harness fullFormDirty onEditFull={onEditFull} />);
    await userEvent.click(screen.getByRole("button", { name: "edytuj czego szukamy" }));
    expect(screen.queryByTestId("drawer")).toBeNull();
    expect(onEditFull).toHaveBeenCalledWith("champion-section-stack");
    await userEvent.click(screen.getByRole("button", { name: "brak pytań" }));
    expect(onEditFull).toHaveBeenLastCalledWith("champion-section-screening");
  });

  it("szuflada zlecona przez stronę przy niezapisanym formularzu też idzie do formularza", () => {
    const onEditFull = vi.fn();
    const onEditBlockChange = vi.fn();
    render(
      <Harness
        fullFormDirty
        editBlock="search"
        onEditBlockChange={onEditBlockChange}
        onEditFull={onEditFull}
      />,
    );
    expect(screen.queryByTestId("drawer")).toBeNull();
    expect(onEditBlockChange).toHaveBeenCalledWith(null);
    expect(onEditFull).toHaveBeenCalledWith("champion-section-stack");
  });

  it("szufladę może sterować strona (okno „Kandydaci do dodania”)", () => {
    render(<Harness editBlock="search" onEditBlockChange={() => undefined} />);
    expect(screen.getByTestId("drawer")).toHaveAttribute("data-block", "search");
  });
});

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyLeagueWidget } from "@/components/v2/league/MyLeagueWidget";
import {
  LEAGUE_FIXTURE_ME,
  LEAGUE_RECRUITER_FOURTH,
  LEAGUE_SPECTATOR,
} from "@/components/v2/league/league-fixtures";
import type { MyLeague } from "@/lib/insights-races-api";

const state = vi.hoisted(() => ({
  data: undefined as MyLeague | undefined,
  isError: false,
  refetch: vi.fn(),
}));

vi.mock("@/hooks/useMyLeague", () => ({
  useMyLeague: () => ({ data: state.data, isError: state.isError, refetch: state.refetch }),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (s: { user: { id: number } }) => unknown) => select({ user: { id: LEAGUE_FIXTURE_ME } }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, onClick }: { children: React.ReactNode; href: string; onClick?: () => void }) => (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        onClick?.();
      }}
    >
      {children}
    </a>
  ),
}));

beforeEach(() => {
  state.data = undefined;
  state.isError = false;
  state.refetch.mockReset();
  window.localStorage.clear();
});

describe("MyLeagueWidget", () => {
  it("przed odpowiedzią i bez dostępu do Insights nie rysuje nic", () => {
    const { container } = render(<MyLeagueWidget />);
    expect(container).toBeEmptyDOMElement();
  });

  it("rekruter: przycisk mówi miejsce i punkty, panel otwiera się kliknięciem", async () => {
    state.data = LEAGUE_RECRUITER_FOURTH;
    render(<MyLeagueWidget />);
    const button = screen.getByRole("button", { name: /^Liga Mistrzów, Q4 2026: 4\. miejsce, 385 punktów/ });
    expect(within(button).getByText("4")).toBeInTheDocument();
    expect(within(button).getByText("385 pkt")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(button);
    const panel = await screen.findByRole("dialog", { name: "Liga Mistrzów · Q4 2026" });
    expect(within(panel).getByText("Do podium brakuje 85 pkt.")).toBeInTheDocument();
    expect(within(panel).getByText("To 1 placement albo 6 rozmów u klienta.")).toBeInTheDocument();
    const me = within(panel).getByRole("listitem", { current: true });
    expect(me).toHaveTextContent("Ty");
    expect(within(panel).getByRole("link", { name: "Cała liga →" })).toHaveAttribute(
      "href",
      "/insights?tab=rywalizacja",
    );
  });

  it("klik w link zamyka panel", async () => {
    state.data = LEAGUE_RECRUITER_FOURTH;
    render(<MyLeagueWidget />);
    await userEvent.click(screen.getByRole("button", { name: /^Liga Mistrzów/ }));
    const panel = await screen.findByRole("dialog");
    await userEvent.click(within(panel).getByRole("link", { name: "Cała liga →" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("kto nie gra: lider ligi", () => {
    state.data = LEAGUE_SPECTATOR;
    render(<MyLeagueWidget />);
    const button = screen.getByRole("button", { name: /prowadzi Marta Wiśniewska, 640 punktów/ });
    expect(within(button).getByText("Marta W.")).toBeInTheDocument();
  });

  it("awaria bez danych to „—” i „Ponów”, nigdy „0 pkt”", async () => {
    state.isError = true;
    render(<MyLeagueWidget />);
    const button = screen.getByRole("button", { name: "Liga Mistrzów: nie udało się wczytać." });
    expect(within(button).getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/0 pkt/)).not.toBeInTheDocument();
    await userEvent.click(button);
    await userEvent.click(await screen.findByRole("button", { name: "Ponów" }));
    expect(state.refetch).toHaveBeenCalledTimes(1);
  });

  it("awans od pierwszego widoku dnia pokazuje strzałkę", () => {
    window.localStorage.setItem(
      `nexus:league-rank:${LEAGUE_FIXTURE_ME}`,
      JSON.stringify({
        day: new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw" }).format(new Date()),
        league: "quarterly_champions_recruiter:Q4 2026",
        rank: 6,
      }),
    );
    state.data = LEAGUE_RECRUITER_FOURTH;
    render(<MyLeagueWidget />);
    expect(screen.getByText("z 6.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dziś awans z 6\. miejsca\.$/ })).toBeInTheDocument();
  });
});

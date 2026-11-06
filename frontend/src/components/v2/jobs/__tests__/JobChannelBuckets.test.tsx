/**
 * Koszyki „Baza” / „LinkedIn” w okienku zespołu (decyzja Artura 06.11.2026,
 * wariant B): pusty koszyk z planem świeci, rekruter przenosi tylko siebie,
 * a rekruter spoza zespołu, który rusza karty, jest ostrzeżeniem.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobChannelBuckets } from "@/components/v2/jobs/JobChannelBuckets";
import type { JobRecruiter } from "@/lib/job-team";

const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: apiMock, api: apiMock }));

const person = (
  user_id: number,
  name: string,
  channel: JobRecruiter["channel"],
): JobRecruiter => ({
  user_id,
  name,
  via: "collaborator",
  proposed: false,
  assigned_by_name: null,
  channel,
});

const TEAM = [
  person(1, "Bartek Testowy", "base"),
  person(2, "Celina Wzorcowa", "base"),
  person(3, "Daria Przykładowa", null),
];

function renderBuckets(props: Partial<React.ComponentProps<typeof JobChannelBuckets>> = {}) {
  const run = vi.fn(async (_key: string, action: () => Promise<unknown>) => {
    await action();
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <JobChannelBuckets
        jobId={11}
        working={TEAM}
        plan={{ base: null, linkedin: 1 }}
        canStaff={false}
        canJoin={false}
        meId={3}
        run={run}
        pending={null}
        onRemove={() => {}}
        canRemove={() => false}
        {...props}
      />
    </QueryClientProvider>,
  );
  return run;
}

beforeEach(() => {
  for (const mock of Object.values(apiMock)) mock.mockReset();
  apiMock.get.mockResolvedValue({ data: [] });
  apiMock.put.mockResolvedValue({ data: {} });
  apiMock.post.mockResolvedValue({ data: {} });
});

describe("JobChannelBuckets", () => {
  it("rozkłada osoby na koszyki, a pusty koszyk z planem mówi, ilu brakuje", () => {
    renderBuckets();
    const base = screen.getByRole("region", { name: "Koszyk Baza" });
    expect(within(base).getByText("Bartek Testowy")).toBeInTheDocument();
    expect(within(base).getByText("Celina Wzorcowa")).toBeInTheDocument();
    const linkedin = screen.getByRole("region", { name: "Koszyk LinkedIn" });
    expect(within(linkedin).getByText("0 z 1")).toBeInTheDocument();
    expect(within(linkedin).getByText("Brakuje: 1 osoba.")).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Bez koszyka" })).getByText("Daria Przykładowa"),
    ).toBeInTheDocument();
  });

  it("rekruter wybiera koszyk tylko sobie; planu nie ustawia", async () => {
    const user = userEvent.setup();
    renderBuckets();
    expect(
      screen.queryByRole("button", { name: "Przenieś Bartek Testowy do koszyka LinkedIn" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /plan koszyków/ })).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Przenieś Daria Przykładowa do koszyka LinkedIn" }),
    );
    expect(apiMock.put).toHaveBeenCalledWith("/api/jobs/11/channels/3", { channel: "linkedin" });
  });

  it("rola przydzielająca przenosi każdego i zapisuje plan", async () => {
    const user = userEvent.setup();
    renderBuckets({ canStaff: true, meId: 99 });
    await user.click(
      screen.getByRole("button", { name: "Przenieś Bartek Testowy do koszyka LinkedIn" }),
    );
    expect(apiMock.put).toHaveBeenCalledWith("/api/jobs/11/channels/1", { channel: "linkedin" });

    await user.click(screen.getByRole("button", { name: "Zmień plan koszyków" }));
    const base = screen.getByRole("textbox", { name: "Baza" });
    await user.clear(base);
    await user.type(base, "2");
    await user.click(screen.getByRole("button", { name: "Zapisz plan" }));
    expect(apiMock.put).toHaveBeenCalledWith("/api/jobs/11/channel-plan", { base: 2, linkedin: 1 });
  });

  it("plan spoza 0–20 nie idzie na serwer", async () => {
    const user = userEvent.setup();
    renderBuckets({ canStaff: true, meId: 99 });
    await user.click(screen.getByRole("button", { name: "Zmień plan koszyków" }));
    await user.type(screen.getByRole("textbox", { name: "Baza" }), "25");
    expect(screen.getByText("Wpisz liczbę od 0 do 20 albo zostaw puste.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz plan" })).toBeDisabled();
  });

  it("rekruter spoza zespołu, który rusza karty, to ostrzeżenie z dodaniem do koszyka", async () => {
    const user = userEvent.setup();
    apiMock.get.mockResolvedValue({ data: [{ user_id: 40, name: "Ola Spoza", cards: 3 }] });
    renderBuckets({ canStaff: true, meId: 99 });
    const notice = await screen.findByRole("region", { name: "Pracują bez przypisania" });
    expect(within(notice).getByText("Ola Spoza")).toBeInTheDocument();
    expect(within(notice).getByText("3 karty w 30 dni")).toBeInTheDocument();
    await user.click(within(notice).getByRole("button", { name: "Do LinkedIna" }));
    expect(apiMock.post).toHaveBeenCalledWith("/api/jobs/11/collaborators", {
      user_id: 40,
      channel: "linkedin",
    });
  });

  it("rekruter dołącza do wybranego koszyka jednym przyciskiem", async () => {
    const user = userEvent.setup();
    renderBuckets({ canJoin: true, meId: 50 });
    await user.click(screen.getByRole("button", { name: "Dołącz do bazy" }));
    expect(apiMock.post).toHaveBeenCalledWith("/api/jobs/11/collaborators", {
      user_id: 50,
      channel: "base",
    });
  });
});

/**
 * „Ogłoszenia do nadrobienia” (27.10.2026): lista z maila zbiorczego.
 * Awaria nie wygląda jak pusta lista, filtr „Do zrobienia przeze mnie”,
 * okno ogłoszenia na pierwszym brakującym kanale osoby. Dane fikcyjne.
 */

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import type { AdChannelView, MissingAdsItem } from "@/lib/api/jobAd";

import { MissingAdsQueue, channelText, firstMine, type MissingAdsQueueApi } from "../MissingAdsQueue";

function channel(patch: Partial<AdChannelView> & Pick<AdChannelView, "channel">): AdChannelView {
  return {
    state: "missing",
    since: null,
    mine: false,
    owner_names: [],
    skip_reason: null,
    skipped_by_name: null,
    ...patch,
  };
}

const MINE: MissingAdsItem = {
  job_id: 11,
  title: "Analityk Przykładowy",
  client: "Klient A",
  opened_at: "2026-10-20T08:00:00Z",
  backlog: true,
  channels: [
    channel({ channel: "kariera", owner_names: ["Julia Przykładowa"] }),
    channel({ channel: "pracuj", mine: true }),
    channel({ channel: "jjit", state: "live", since: "2026-10-22T08:00:00Z" }),
  ],
};

const WATCHED: MissingAdsItem = {
  job_id: 12,
  title: "Tester Przykładowy",
  client: "Klient B",
  opened_at: "2026-10-21T08:00:00Z",
  backlog: false,
  channels: [
    channel({ channel: "kariera", owner_names: ["Ola Przykładowa"] }),
    channel({ channel: "pracuj", state: "skipped", skip_reason: "Bez Pracuj" }),
    channel({ channel: "jjit", state: "live", since: "2026-10-22T08:00:00Z" }),
  ],
};

function setup(missing: MissingAdsQueueApi["missing"]) {
  const api = { missing: vi.fn(missing) } as unknown as MissingAdsQueueApi;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MissingAdsQueue api={api} />
    </QueryClientProvider>,
  );
  return api;
}

describe("MissingAdsQueue", () => {
  it("domyślnie pokazuje tylko rekrutacje z brakiem osoby", async () => {
    setup(async () => [MINE, WATCHED]);
    expect(await screen.findByRole("button", { name: /Do zrobienia przeze mnie · 1/ })).toBeTruthy();
    expect(screen.getAllByText("Analityk Przykładowy").length).toBeGreaterThan(0);
    expect(screen.queryByText("Tester Przykładowy")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Także pilnowane · 2/ }));
    expect(screen.getByText("Tester Przykładowy")).toBeTruthy();
  });

  it("awaria pokazuje błąd i „Spróbuj ponownie”, nie pustą listę", async () => {
    setup(async () => {
      throw new Error("down");
    });
    expect(await screen.findByText("Nie udało się wczytać listy")).toBeTruthy();
    expect(screen.queryByText(/Nic nie czeka na Ciebie/)).toBeNull();
  });

  it("pusta lista mówi, że nic nie czeka", async () => {
    setup(async () => []);
    expect(await screen.findByText(/Nic nie czeka na Ciebie/)).toBeTruthy();
  });

  it("okno otwiera się na pierwszym brakującym kanale osoby", () => {
    expect(firstMine(MINE)).toBe("pracuj");
    expect(firstMine(WATCHED)).toBeNull();
    expect(channelText(MINE.channels[0])).toBe("Brak · robi Julia P.");
    expect(channelText(MINE.channels[1])).toBe("Brak · robisz Ty");
    expect(channelText(WATCHED.channels[1])).toBe("Nie publikujemy: Bez Pracuj");
  });
});

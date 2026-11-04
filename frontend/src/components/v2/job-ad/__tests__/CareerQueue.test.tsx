/**
 * „Strona kariery do uzupełnienia” (21.10.2026): każdą treść czyta człowiek,
 * publikacja idzie z wersją z ekranu, po niej od razu następna rekrutacja,
 * a awaria listy nie wygląda jak „wszystko zrobione”.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import type { CareerQueue as Queue, CareerQueueItem, JobAdState } from "@/lib/api/jobAd";

import { CareerQueue, type CareerQueueApi } from "../CareerQueue";
import { CareerQueueLink } from "../CareerQueueLink";
import { adState, CLIENT_FINDING, CONTENT, EMPTY_STATE } from "./job-ad-fixtures";

const ITEM: CareerQueueItem = {
  job_id: 11,
  title: "Senior Java Developer — płatności",
  city: "Warszawa",
  remote_policy: "hybrid",
  delivery_lead_name: "Gosia Przykładowa",
  opened_at: "2026-10-18T09:00:00Z",
  ad: "ready",
};
const SECOND: CareerQueueItem = { ...ITEM, job_id: 12, title: "DevOps Engineer (AWS)" };

function queue(items: CareerQueueItem[], patch: Partial<Queue> = {}): Queue {
  return { scope: "mine", mine_count: items.length, all_count: items.length, items, ...patch };
}

function setup(
  load: (scope: "mine" | "all") => Queue | Error,
  ads: Record<number, JobAdState> = { 11: adState(), 12: adState() },
) {
  const api = {
    careerQueue: vi.fn(async (scope: "mine" | "all") => {
      const result = load(scope);
      if (result instanceof Error) throw result;
      return result;
    }),
    get: vi.fn(async (jobId: number) => ads[jobId] ?? EMPTY_STATE),
    generate: vi.fn(async () => adState()),
    save: vi.fn(async () => adState()),
    markPublished: vi.fn(async () => adState()),
    markRemoved: vi.fn(async () => adState()),
    publishCareer: vi.fn(async () =>
      adState({
        career: {
          status: "live",
          url: "https://kariera.b2bnetwork.pl/r/senior-java-developer-ab12",
          published_at: "2026-10-21T09:00:00Z",
          published_by_name: "Marta Przykładowa",
        },
      }),
    ),
  } satisfies CareerQueueApi;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CareerQueue api={api} />
    </QueryClientProvider>,
  );
  return api;
}

beforeEach(() => vi.clearAllMocks());

describe("CareerQueue", () => {
  it("„Opublikuj i następna” publikuje wersję z ekranu i przechodzi dalej", async () => {
    const api = setup(() => queue([ITEM, SECOND]));
    const pane = await screen.findByRole("region", { name: "Treść na stronę kariery" });
    expect(await within(pane).findByText(CONTENT.lead)).toBeInTheDocument();

    fireEvent.click(within(pane).getByRole("button", { name: "Opublikuj i następna" }));
    await waitFor(() =>
      expect(api.publishCareer).toHaveBeenCalledWith(11, "2026-10-12T09:20:00Z"),
    );
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(12));
    expect(screen.getByText("Opublikowane teraz: 1")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Rekrutacje bez strony kariery" });
    expect(
      within(list).getByRole("button", { name: /DevOps Engineer/ }),
    ).toHaveAttribute("aria-current", "true");
  });

  it("fragment blokujący wyłącza publikację i jest nazwany", async () => {
    setup(() => queue([ITEM]), {
      11: adState({
        content: { ...CONTENT, about: "Platforma płatności dla klienta Bank Przykładowy." },
        findings: [CLIENT_FINDING],
      }),
    });
    const pane = await screen.findByRole("region", { name: "Treść na stronę kariery" });
    expect(await within(pane).findByRole("alert")).toHaveTextContent(CLIENT_FINDING.message);
    expect(within(pane).getByRole("button", { name: "Opublikuj i następna" })).toBeDisabled();
  });

  it("rekrutacja bez treści proponuje „Przygotuj treść”", async () => {
    const api = setup(() => queue([{ ...ITEM, ad: "missing" }]), { 11: EMPTY_STATE });
    fireEvent.click(await screen.findByRole("button", { name: "Przygotuj treść" }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith(11, "pl", null));
  });

  it("bez „swoich” rekrutacji od razu pokazuje wszystkie", async () => {
    const api = setup((scope) =>
      scope === "mine"
        ? queue([], { mine_count: 0, all_count: 2 })
        : queue([ITEM, SECOND], { scope: "all", mine_count: 0 }),
    );
    await waitFor(() => expect(api.careerQueue).toHaveBeenCalledWith("all"));
    expect(await screen.findByRole("button", { name: "Wszystkie · 2" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("awaria listy nie wygląda jak „wszystko zrobione”", async () => {
    setup(() => new Error("500"));
    expect(await screen.findByText("Nie udało się wczytać listy")).toBeInTheDocument();
    expect(screen.queryByText(/mają stronę kariery/)).not.toBeInTheDocument();
  });

  it("pusta lista mówi, że wszystko wisi", async () => {
    setup(() => queue([], { mine_count: 0, all_count: 0 }));
    expect(
      await screen.findByText("Wszystkie Twoje otwarte rekrutacje mają stronę kariery."),
    ).toBeInTheDocument();
  });
});

describe("CareerQueueLink", () => {
  function renderLink(result: Queue | Error) {
    const api = {
      careerQueue: vi.fn(async () => {
        if (result instanceof Error) throw result;
        return result;
      }),
    };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <CareerQueueLink api={api} />
      </QueryClientProvider>,
    );
    return api;
  }

  it("pokazuje liczbę „swoich” rekrutacji bez strony i prowadzi do kolejki", async () => {
    const api = renderLink(queue([], { mine_count: 12, all_count: 203 }));
    const link = await screen.findByTestId("career-queue-link");
    expect(link).toHaveTextContent("Strona kariery · 12");
    expect(link).toHaveAttribute("href", "/jobs/strona-kariery");
    expect(api.careerQueue).toHaveBeenCalledWith("mine", 0);
  });

  it("bez rekrutacji albo bez prawa (403) nie ma przycisku", async () => {
    const api = renderLink(new Error("403"));
    await waitFor(() => expect(api.careerQueue).toHaveBeenCalled());
    expect(screen.queryByTestId("career-queue-link")).toBeNull();
  });
});

/**
 * Krok „Ogłoszenie” zaraz po utworzeniu rekrutacji (23.11.2026): kanały jak
 * w ostatnich rekrutacjach klienta, widełki wpisane raz dla JustJoin.IT
 * i maila do opiekuna Pracuj.pl, jedno „Opublikuj w N miejscach”.
 */

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import type {
  AdChannelView,
  AdJjitApi,
  AdRecentChannels,
  AdReminders,
  JobAdState,
} from "@/lib/api/jobAd";
import type { PortalListingOptions } from "@/lib/api/jobPortals";

import {
  AfterCreatePublish,
  channelRows,
  initialSelection,
  parseSalary,
  publishAfterCreate,
  type AfterCreateApi,
} from "../AfterCreatePublish";
import { adState } from "./job-ad-fixtures";

const view = (channel: AdChannelView["channel"]): AdChannelView => ({
  channel,
  state: "missing",
  since: null,
  mine: true,
  owner_names: [],
  skip_reason: null,
  skipped_by_name: null,
});

const LEAD: AdReminders = {
  can_manage: true,
  recruiter_names: [],
  channels: [view("kariera"), view("pracuj"), view("jjit")],
};

const JJIT: AdJjitApi = {
  ready: true,
  status: null,
  pending_action: null,
  last_error: null,
  options: null,
  career_required: true,
};

const DEFAULTS: PortalListingOptions = {
  category: null,
  experience_level: "senior",
  working_time: "full_time",
  workplace_type: "remote",
  office_days: null,
  city: "Warszawa",
  salary: null,
};

const LIVE = { status: "live" as const, url: "https://kariera.example/r/x", published_at: null, published_by_name: null };

function leadState(recent: AdRecentChannels | null = null): JobAdState {
  return { ...adState({ reminders: LEAD, jjit_api: JJIT }), recent_channels: recent };
}

function fakeApi(state: JobAdState) {
  const published = { ...state, career: LIVE };
  return {
    publishCareer: vi.fn<AfterCreateApi["publishCareer"]>(async () => published),
    publishJjit: vi.fn<AfterCreateApi["publishJjit"]>(async () => published),
    sendPracujMail: vi.fn<AfterCreateApi["sendPracujMail"]>(async () => published),
    previewPracujMail: vi.fn<AfterCreateApi["previewPracujMail"]>(),
    save: vi.fn<AfterCreateApi["save"]>(),
  } satisfies AfterCreateApi;
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("kanały kroku „Ogłoszenie”", () => {
  it("zaznacza kanały z ostatnich rekrutacji klienta, które da się opublikować", () => {
    const state = leadState({ channels: ["kariera", "jjit"], jobs: 4, jjit_category: "java" });
    const rows = channelRows(state, { publishBlockedReason: null });
    expect(initialSelection(rows, state)).toEqual(["kariera", "jjit"]);
  });

  it("klient bez historii = wszystkie kanały", () => {
    const state = leadState({ channels: ["kariera", "jjit", "pracuj"], jobs: 0, jjit_category: null });
    expect(initialSelection(channelRows(state, { publishBlockedReason: null }), state)).toEqual([
      "kariera",
      "jjit",
      "pracuj",
    ]);
  });

  it("rekruter publikuje tylko stronę kariery; portale robi DL", () => {
    const state = {
      ...adState({ reminders: { ...LEAD, can_manage: false }, jjit_api: JJIT }),
      recent_channels: null,
    };
    const rows = channelRows(state, { publishBlockedReason: null });
    expect(rows.map((r) => [r.channel, r.unavailable])).toEqual([
      ["kariera", null],
      ["jjit", "Publikuje Delivery Lead rekrutacji."],
      ["pracuj", "Publikuje Delivery Lead rekrutacji."],
    ]);
    expect(initialSelection(rows, state)).toEqual(["kariera"]);
  });
});

describe("widełki wpisane raz", () => {
  it("jedna granica to stała stawka, pusto = bez widełek", () => {
    expect(parseSalary("", "")).toEqual({ salary: null, error: null });
    expect(parseSalary("150", "")).toEqual({
      salary: { from: 150, to: 150, unit: "hour" },
      error: null,
    });
    expect(parseSalary("150", "190").salary).toEqual({ from: 150, to: 190, unit: "hour" });
  });

  it("odwrócona albo ponad trzykrotna rozpiętość to błąd", () => {
    expect(parseSalary("190", "150").error).toMatch(/nie może być niższa/);
    expect(parseSalary("50", "200").error).toMatch(/trzy razy/);
  });

  it("te same widełki idą do JustJoin.IT i do maila Pracuj.pl", async () => {
    const state = leadState({ channels: ["kariera", "jjit", "pracuj"], jobs: 3, jjit_category: "java" });
    const api = fakeApi(state);
    const result = await publishAfterCreate({
      jobId: 7,
      state,
      selected: ["kariera", "jjit", "pracuj"],
      salary: { from: 150, to: 190, unit: "hour" },
      noSalaryReason: null,
      api,
      listingDefaults: async () => DEFAULTS,
      requestId: "req-1",
    });

    expect(result.outcomes).toEqual({
      kariera: { status: "done" },
      jjit: { status: "done" },
      pracuj: { status: "done" },
    });
    expect(api.publishCareer).toHaveBeenCalledWith(7, "2026-10-12T09:20:00Z");
    expect(api.publishJjit).toHaveBeenCalledWith(7, {
      expected_updated_at: "2026-10-12T09:20:00Z",
      options: {
        ...DEFAULTS,
        category: "java",
        salary: { from: 150, to: 190, unit: "hour" },
        no_salary_reason: null,
      },
    });
    expect(api.sendPracujMail).toHaveBeenCalledWith(7, {
      rate_from: 150,
      rate_to: 190,
      expected_updated_at: "2026-10-12T09:20:00Z",
      client_request_id: "req-1",
    });
  });

  it("bez kategorii JJIT i bez stawki dla Pracuj.pl kanał czeka na „Dokończ”", async () => {
    const state = leadState({ channels: ["kariera", "jjit", "pracuj"], jobs: 3, jjit_category: null });
    const api = fakeApi(state);
    const result = await publishAfterCreate({
      jobId: 7,
      state,
      selected: ["kariera", "jjit", "pracuj"],
      salary: null,
      noSalaryReason: "Stawkę podajemy na rozmowie.",
      api,
      listingDefaults: async () => DEFAULTS,
      requestId: "req-1",
    });

    expect(result.outcomes.kariera).toEqual({ status: "done" });
    expect(result.outcomes.jjit?.status).toBe("finish");
    expect(result.outcomes.pracuj?.status).toBe("finish");
    expect(api.publishJjit).not.toHaveBeenCalled();
    expect(api.sendPracujMail).not.toHaveBeenCalled();
  });

  it("odmowa strony kariery nie wysyła JJIT w trybie linku, Pracuj.pl idzie dalej", async () => {
    const state = leadState({ channels: ["kariera", "jjit", "pracuj"], jobs: 3, jjit_category: "java" });
    const api = fakeApi(state);
    api.publishCareer.mockRejectedValueOnce(new Error("422"));
    const result = await publishAfterCreate({
      jobId: 7,
      state,
      selected: ["kariera", "jjit", "pracuj"],
      salary: { from: 150, to: 190, unit: "hour" },
      noSalaryReason: null,
      api,
      listingDefaults: async () => DEFAULTS,
      requestId: "req-1",
    });

    expect(result.outcomes.kariera?.status).toBe("error");
    expect(result.outcomes.jjit?.status).toBe("error");
    expect(result.outcomes.pracuj).toEqual({ status: "done" });
    expect(api.publishJjit).not.toHaveBeenCalled();
  });
});

describe("panel „Gdzie publikujemy”", () => {
  it("jedno pole widełek i „Opublikuj w 3 miejscach”", async () => {
    const state = leadState({ channels: ["kariera", "jjit", "pracuj"], jobs: 5, jjit_category: "java" });
    const api = fakeApi(state);
    wrap(
      <AfterCreatePublish
        jobId={7}
        state={state}
        waitingReason={null}
        publishBlockedReason={null}
        onLater={vi.fn()}
        onShowChannels={vi.fn()}
        onStateChange={vi.fn()}
        api={api}
        listingDefaults={async () => DEFAULTS}
      />,
    );

    expect(screen.getByText(/jak w 5 ostatnich rekrutacjach/)).toBeInTheDocument();
    expect(screen.getAllByLabelText(/Widełki (od|do)/)).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Widełki od"), { target: { value: "150" } });
    fireEvent.change(screen.getByLabelText("Widełki do"), { target: { value: "190" } });
    const start = screen.getByTestId("after-create-publish-start");
    expect(start.textContent).toBe("Opublikuj w 3 miejscach");
    fireEvent.click(start);

    await waitFor(() => expect(api.sendPracujMail).toHaveBeenCalled());
    expect(api.publishJjit.mock.calls[0][1].options?.salary).toEqual({ from: 150, to: 190, unit: "hour" });
    expect(api.sendPracujMail.mock.calls[0][1]).toMatchObject({ rate_from: 150, rate_to: 190 });
    expect(await screen.findAllByText("Zrobione")).toHaveLength(3);
  });

  it("bez widełek JustJoin.IT pyta o powód, „Wróć” niczego nie wysyła", async () => {
    const state = leadState({ channels: ["kariera", "jjit"], jobs: 2, jjit_category: "java" });
    const api = fakeApi(state);
    wrap(
      <AfterCreatePublish
        jobId={7}
        state={state}
        waitingReason={null}
        publishBlockedReason={null}
        onLater={vi.fn()}
        onShowChannels={vi.fn()}
        onStateChange={vi.fn()}
        api={api}
        listingDefaults={async () => DEFAULTS}
      />,
    );

    fireEvent.click(screen.getByTestId("after-create-publish-start"));
    expect(await screen.findByText("Ogłoszenie bez widełek")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Wróć i wpisz widełki" }));
    await waitFor(() => expect(screen.queryByText("Ogłoszenie bez widełek")).not.toBeInTheDocument());
    expect(api.publishCareer).not.toHaveBeenCalled();
    expect(api.publishJjit).not.toHaveBeenCalled();
  });

  it("„Później” zamyka krok, a do czasu treści przycisk czeka", () => {
    const onLater = vi.fn();
    const state = leadState(null);
    wrap(
      <AfterCreatePublish
        jobId={7}
        state={state}
        waitingReason="Czekam na treść ogłoszenia…"
        publishBlockedReason={null}
        onLater={onLater}
        onShowChannels={vi.fn()}
        onStateChange={vi.fn()}
        api={fakeApi(state)}
      />,
    );

    expect(screen.getByTestId("after-create-publish-start")).toBeDisabled();
    expect(screen.getByText("Czekam na treść ogłoszenia…")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("after-create-later"));
    expect(onLater).toHaveBeenCalled();
  });
});

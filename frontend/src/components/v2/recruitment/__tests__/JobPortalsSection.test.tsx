import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }));

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import { JobPortalsSection, portalRowStatus } from "../JobPortalsSection";
import {
  EMPTY_LISTING_OPTIONS,
  isLive,
  jobPortalKeys,
  latestPosting,
  type JobPostingRead,
  type PortalConfigResponse,
  type PortalListingOptions,
} from "@/lib/api/jobPortals";

function renderWith(
  config: PortalConfigResponse | undefined,
  postings: JobPostingRead[] = [],
  defaults?: PortalListingOptions,
) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  if (config) qc.setQueryData(jobPortalKeys.config, config);
  qc.setQueryData(jobPortalKeys.postings(5), postings);
  if (defaults) qc.setQueryData(jobPortalKeys.listingDefaults(5), defaults);
  qc.setQueryData(jobPortalKeys.dictionaries("rocketjobs"), {
    categories: [{ key: "java", name: "Java" }],
    experience_levels: [],
    working_times: [],
    workplace_types: [],
  });
  return render(
    <QueryClientProvider client={qc}>
      <JobPortalsSection jobId={5} readOnly={false} defaultOpen pollWhilePublishingMs={false} />
    </QueryClientProvider>,
  );
}

const OFF: PortalConfigResponse = {
  any_ready: false,
  portals: [
    { portal: "pracuj_pl", label: "Pracuj.pl", state: "disabled", enabled: false },
    { portal: "justjoinit", label: "JustJoinIT", state: "disabled", enabled: false },
  ],
};
const ON: PortalConfigResponse = {
  any_ready: true,
  portals: [
    { portal: "pracuj_pl", label: "Pracuj.pl", state: "ready", enabled: true },
    { portal: "justjoinit", label: "JustJoinIT", state: "misconfigured", enabled: true },
  ],
};

const failed: JobPostingRead = {
  id: 1,
  portal: "pracuj_pl",
  status: "failed",
  external_id: null,
  url: null,
  published_at: null,
  last_synced_at: null,
  last_error: "Integracja z Pracuj.pl czeka na dokumentację API portalu.",
  attempts: 1,
  created_at: null,
  updated_at: null,
};

describe("JobPortalsSection — wejście z ?tab=portals (R5-8)", () => {
  it("rozwija i przewija sekcję, gdy tylko pojawi się konfiguracja", () => {
    const scroll = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scroll;
    try {
      const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
      qc.setQueryData(jobPortalKeys.config, ON);
      qc.setQueryData(jobPortalKeys.postings(5), [failed]);
      render(
        <QueryClientProvider client={qc}>
          <JobPortalsSection jobId={5} readOnly={false} focusOnReady pollWhilePublishingMs={false} />
        </QueryClientProvider>,
      );
      expect(screen.getByRole("button", { name: /Portale ogłoszeniowe/ })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
      expect(scroll).toHaveBeenCalledTimes(1);
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it("bez wejścia z linku sekcja zostaje zwinięta", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
    qc.setQueryData(jobPortalKeys.config, ON);
    render(
      <QueryClientProvider client={qc}>
        <JobPortalsSection jobId={5} readOnly={false} pollWhilePublishingMs={false} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: /Portale ogłoszeniowe/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});

describe("JobPortalsSection", () => {
  it("renders nothing while every portal is disabled (production today)", () => {
    const { container } = renderWith(OFF);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the config is unknown", () => {
    const { container } = renderWith(undefined);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows ready portals with actions and the failure reason", () => {
    renderWith(ON, [failed]);
    expect(screen.getByText("Portale ogłoszeniowe")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("czeka na dokumentację API");
    expect(screen.getByRole("button", { name: "Wyślij ponownie" })).toBeInTheDocument();
    expect(screen.getByText("Portal nie jest skonfigurowany")).toBeInTheDocument();
  });
});

const BOARDS: PortalConfigResponse = {
  any_ready: true,
  portals: [
    { portal: "rocketjobs", label: "RocketJobs", state: "ready", enabled: true },
    { portal: "justjoinit", label: "JustJoin.IT", state: "not_connected", enabled: true },
  ],
};

const DEFAULTS: PortalListingOptions = {
  ...EMPTY_LISTING_OPTIONS,
  experience_level: "senior",
  working_time: "full_time",
  city: "Warszawa",
  workplace_type: "hybrid",
  office_days: 2,
};

describe("JobPortalsSection — RocketJobs / JustJoin.IT", () => {
  it("niepołączony portal mówi, gdzie połączyć konto (bez linku dla nie-admina)", () => {
    renderWith(BOARDS);
    expect(screen.getByText(/Konto portalu niepołączone —/)).toHaveTextContent(
      "Ustawienia → Portale ogłoszeniowe",
    );
    expect(screen.queryByRole("link", { name: /Portale ogłoszeniowe/ })).toBeNull();
  });

  it("„Opublikuj” otwiera okno z domyślnymi z rekrutacji i blokuje wysyłkę bez kategorii", async () => {
    renderWith(BOARDS, [], DEFAULTS);
    fireEvent.click(screen.getByRole("button", { name: "Opublikuj" }));
    expect(await screen.findByText("Opublikuj na RocketJobs")).toBeInTheDocument();
    expect(screen.getByLabelText("Miasto")).toHaveValue("Warszawa");
    expect(screen.getByLabelText("Dni w biurze w tygodniu")).toHaveValue(2);
    const dialogButtons = screen.getAllByRole("button", { name: "Opublikuj" });
    fireEvent.click(dialogButtons[dialogButtons.length - 1]);
    expect(await screen.findByText("Wybierz kategorię ogłoszenia.")).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("wysyła publikację z parametrami ogłoszenia", async () => {
    apiMock.post.mockResolvedValueOnce({ data: { ...failed, portal: "rocketjobs", status: "publishing" } });
    renderWith(BOARDS, [], DEFAULTS);
    fireEvent.click(screen.getByRole("button", { name: "Opublikuj" }));
    fireEvent.change(await screen.findByLabelText("Kategoria"), { target: { value: "java" } });
    const dialogButtons = screen.getAllByRole("button", { name: "Opublikuj" });
    fireEvent.click(dialogButtons[dialogButtons.length - 1]);
    await waitFor(() => expect(apiMock.post).toHaveBeenCalled());
    expect(apiMock.post).toHaveBeenCalledWith("/api/jobs/5/portals/rocketjobs/publish", {
      options: { ...DEFAULTS, category: "java" },
    });
  });

  it("żywe ogłoszenie ma edycję i etykietę kolejki", () => {
    const live: JobPostingRead = {
      ...failed,
      portal: "rocketjobs",
      status: "published",
      last_error: null,
      pending_action: "update",
      options: { ...DEFAULTS, category: "java" },
    };
    renderWith(BOARDS, [live]);
    expect(screen.getByText("Aktualizacja w kolejce")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edytuj ogłoszenie" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wycofaj" })).toBeInTheDocument();
  });

  it("uwaga przy żywym ogłoszeniu jest widoczna (nie tylko przy porażce)", () => {
    const live: JobPostingRead = {
      ...failed,
      portal: "rocketjobs",
      status: "published",
      pending_action: "close",
      last_error: "Połączenie z portalem wygasło — połącz konto ponownie.",
      options: { ...DEFAULTS, category: "java" },
    };
    renderWith(BOARDS, [live]);
    expect(screen.getByRole("status")).toHaveTextContent("Połączenie z portalem wygasło");
  });

  it("status wiersza", () => {
    const cfg = BOARDS.portals[0];
    expect(portalRowStatus({ ...cfg, state: "not_connected" }, null)).toBe("Konto portalu niepołączone");
    expect(portalRowStatus({ ...cfg, state: "misconfigured" }, null)).toBe("Portal nie jest skonfigurowany");
    expect(portalRowStatus(cfg, null)).toBe("Nie publikowano");
    expect(portalRowStatus(cfg, { ...failed, status: "published", pending_action: "close" })).toBe(
      "Zamykanie w kolejce",
    );
    expect(portalRowStatus(cfg, { ...failed, status: "published", pending_action: null })).toBe("Opublikowane");
  });
});

describe("jobPortals helpers", () => {
  it("latest posting per portal and liveness", () => {
    const live = { ...failed, id: 2, status: "publishing" as const };
    expect(latestPosting([live, failed], "pracuj_pl")?.id).toBe(2);
    expect(latestPosting([live], "justjoinit")).toBeNull();
    expect(isLive(live)).toBe(true);
    expect(isLive(failed)).toBe(false);
    expect(isLive(null)).toBe(false);
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }));

import { JobPortalsSection } from "../JobPortalsSection";
import { isLive, jobPortalKeys, latestPosting, type JobPostingRead, type PortalConfigResponse } from "@/lib/api/jobPortals";

function renderWith(config: PortalConfigResponse | undefined, postings: JobPostingRead[] = []) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  if (config) qc.setQueryData(jobPortalKeys.config, config);
  qc.setQueryData(jobPortalKeys.postings(5), postings);
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

/**
 * Raport komunikatu (M8): „Wyślij ponownie do nieudanych” wraca do kolejki
 * tylko osoby z błędem wysyłki (po potwierdzeniu); „niepewni” nie wracają —
 * raport podaje ich listę do sprawdzenia w skrzynce. Dane fikcyjne.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() }));
vi.mock("@/lib/api", () => ({ api }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));

import { SENT_ID, detail, settings } from "@/app/preview/hr-announcements/fixtures";
import type { AnnouncementDetail } from "@/lib/api/care-announcements";

import { AnnouncementReport } from "../AnnouncementReport";

function sentWithProblems(overrides: Partial<AnnouncementDetail> = {}): AnnouncementDetail {
  const base = detail(SENT_ID, "head");
  const [failed, uncertain, ...rest] = base.recipients;
  return {
    ...base,
    counts: { ...base.counts, sent: 2, failed: 1, uncertain: 1, bounced: 0 },
    recipients: [
      { ...failed, status: "failed", error_code: "http_400", simulated: false },
      { ...uncertain, status: "uncertain", error_code: "http_504", simulated: false },
      ...rest,
    ],
    can_retry_failed: true,
    ...overrides,
  };
}

function renderReport(announcement: AnnouncementDetail) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AnnouncementReport announcement={announcement} settings={settings()} onEdit={vi.fn()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe("AnnouncementReport", () => {
  it("„Wyślij ponownie do nieudanych” po potwierdzeniu woła serwer", async () => {
    const user = userEvent.setup();
    const announcement = sentWithProblems();
    api.post.mockResolvedValue({ data: { ...announcement, status: "queued", can_retry_failed: false } });
    renderReport(announcement);

    await user.click(screen.getByRole("button", { name: "Wyślij ponownie do nieudanych" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/1 osoba z błędem wysyłki/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Wyślij ponownie" }));
    expect(api.post).toHaveBeenCalledWith(`/api/care/announcements/${SENT_ID}/retry-failed`);
  });

  it("niepewni są na liście do sprawdzenia ręcznie", () => {
    const announcement = sentWithProblems();
    renderReport(announcement);
    const list = screen.getByRole("list", { name: "Sprawdź ręcznie w skrzynce administracja@" });
    const uncertain = announcement.recipients[1];
    expect(within(list).getByText(new RegExp(uncertain.name))).toBeInTheDocument();
    expect(within(list).queryByText(new RegExp(announcement.recipients[0].name))).not.toBeInTheDocument();
  });

  it("bez osób z błędem nie ma przycisku ponownej wysyłki", () => {
    renderReport(sentWithProblems({ can_retry_failed: false }));
    expect(screen.queryByRole("button", { name: "Wyślij ponownie do nieudanych" })).not.toBeInTheDocument();
  });
});

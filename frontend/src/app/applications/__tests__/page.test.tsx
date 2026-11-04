import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ApplicationsQueuePage from "../page";
import { applicationSubmissionsApi } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  APPLICATION_SUBMISSIONS_PAGE_LIMIT: 100,
  applicationSubmissionsApi: { list: vi.fn(), resolve: vi.fn() },
}));
vi.mock("@/components/Toast", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

const SUBMISSION = {
  id: 7,
  job_id: 1,
  status: "pending_review",
  submitted_first_name: "Anna",
  submitted_last_name: "Nowak",
  submitted_email: "anna@example.com",
  submitted_phone: null,
  submitted_linkedin: null,
  submitted_message: null,
  matched_candidate_id: null,
  cv_filename: "cv.pdf",
  created_at: new Date().toISOString(),
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ApplicationsQueuePage />
    </QueryClientProvider>,
  );
}

describe("Zgłoszenia: „Utwórz kandydata” na adres trwale usuniętego profilu", () => {
  beforeEach(() => {
    vi.mocked(applicationSubmissionsApi.list).mockResolvedValue([SUBMISSION] as never);
    vi.mocked(applicationSubmissionsApi.resolve)
      .mockReset()
      .mockRejectedValueOnce({
        response: {
          status: 409,
          data: { detail: { code: "candidate_erased", message: "Zdanie serwera" } },
        },
      })
      .mockResolvedValue({ id: 7, status: "created", candidate_id: 9 } as never);
  });

  it("pyta rekrutera i po zgodzie ponawia z potwierdzeniem", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Utwórz kandydata/ }));
    await user.click(await screen.findByRole("button", { name: "Dodaj mimo to" }));

    await waitFor(() =>
      expect(applicationSubmissionsApi.resolve).toHaveBeenLastCalledWith(7, "create", true),
    );
  });

  it("anulowanie nie ponawia zapisu", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Utwórz kandydata/ }));
    await screen.findByRole("button", { name: "Dodaj mimo to" });
    await user.click(screen.getByRole("button", { name: "Anuluj" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Dodaj mimo to" })).not.toBeInTheDocument(),
    );
    expect(applicationSubmissionsApi.resolve).toHaveBeenCalledTimes(1);
  });
});

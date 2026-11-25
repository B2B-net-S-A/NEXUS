/** Pasek „Zasady ze spotkań” na stronie rekrutacji (Insights → Przegrane, 25.11.2026). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ clientRules: vi.fn(), role: "delivery_lead" }));

vi.mock("@/lib/lost-review", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/lost-review")>();
  return { ...actual, lostReviewApi: { ...actual.lostReviewApi, clientRules: mocks.clientRules } };
});

vi.mock("@/store/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/store/auth")>();
  return {
    ...actual,
    useAuthStore: (selector: (s: { user: { role: string; roles: string[] } }) => unknown) =>
      selector({ user: { role: mocks.role, roles: [mocks.role] } }),
  };
});

import { ClientLessonsStrip } from "@/components/v2/jobs/ClientLessonsStrip";

function renderStrip() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ClientLessonsStrip clientId={11} />
    </QueryClientProvider>,
  );
}

describe("ClientLessonsStrip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.role = "delivery_lead";
  });

  it("pokazuje zasady klienta w jednej linii", async () => {
    mocks.clientRules.mockResolvedValue([
      { id: 1, scope: "client", client_id: 11, job_id: null, text: "Pierwsze CV do 48 h", created_at: null },
      { id: 2, scope: "all", client_id: null, job_id: null, text: "Pytamy HM o ocenę", created_at: null },
    ]);
    renderStrip();
    expect(await screen.findByTestId("client-lessons-strip")).toHaveTextContent(
      "Pierwsze CV do 48 h · Pytamy HM o ocenę",
    );
  });

  it("bez zasad nic nie pokazuje", async () => {
    mocks.clientRules.mockResolvedValue([]);
    renderStrip();
    await waitFor(() => expect(mocks.clientRules).toHaveBeenCalledWith(11));
    expect(screen.queryByTestId("client-lessons-strip")).toBeNull();
  });

  it("rekruter nie pyta serwera", () => {
    mocks.role = "recruiter";
    renderStrip();
    expect(mocks.clientRules).not.toHaveBeenCalled();
    expect(screen.queryByTestId("client-lessons-strip")).toBeNull();
  });
});

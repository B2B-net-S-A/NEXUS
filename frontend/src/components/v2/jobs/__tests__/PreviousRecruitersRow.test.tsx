/**
 * Wiersz „Poprzedni rekruter” (14.10.2026): osoby uśpione przy zejściu z P1
 * albo zamknięciu. Wracają same przy P1; rola przydzielająca może usunąć
 * osobę z listy („Usuń z poprzednich” — nie wróci).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreviousRecruitersRow } from "@/components/v2/jobs/PreviousRecruitersRow";
import type { PreviousRecruiter } from "@/lib/job-team";

const deleteMock = vi.fn();
const toast = vi.hoisted(() => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { delete: (...args: unknown[]) => deleteMock(...args) },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const ANNA: PreviousRecruiter = {
  user_id: 21,
  name: "Anna Kowalska",
  via: "owner",
  reason: "priority",
  parked_at: "2026-10-14T13:02:00Z",
  parked_by_name: "Marta Zielińska",
  will_return: true,
};
const EWA: PreviousRecruiter = {
  user_id: 23,
  name: "Ewa Nieaktywna",
  via: "collaborator",
  reason: "priority",
  parked_at: "2026-10-14T13:02:00Z",
  parked_by_name: "Marta Zielińska",
  will_return: false,
};

function renderRow(props: Partial<Parameters<typeof PreviousRecruitersRow>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <PreviousRecruitersRow
        jobId={501}
        people={[ANNA, EWA]}
        canStaff
        closed={false}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { invalidateSpy };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PreviousRecruitersRow", () => {
  it("pokazuje osoby, datę i to, czy wrócą przy P1", () => {
    renderRow();

    const list = screen.getByRole("list", { name: "Poprzedni rekruter" });
    expect(within(list).getByText("Anna Kowalska")).toBeInTheDocument();
    expect(within(list).getByText("do 14.10 · wróci przy P1")).toBeInTheDocument();
    expect(
      within(list).getByText(/nie wróci — konto nieaktywne albo bez roli rekrutera/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Przesunął\(a\) Marta Z\. — zejście z P1\./)).toBeInTheDocument();
  });

  it("przy zamkniętej rekrutacji mówi o otwarciu na P1", () => {
    renderRow({ people: [{ ...ANNA, reason: "closed" }], closed: true });

    expect(screen.getByText("do 14.10 · wróci przy otwarciu na P1")).toBeInTheDocument();
    expect(screen.getByText(/zamknięcie rekrutacji/)).toBeInTheDocument();
  });

  it("bez prawa przydziału nie ma „Usuń z poprzednich”", () => {
    renderRow({ canStaff: false });

    expect(
      screen.queryByRole("button", { name: /Usuń z poprzednich/ }),
    ).not.toBeInTheDocument();
  });

  it("„Usuń z poprzednich” pyta, woła DELETE i odświeża obsadę", async () => {
    deleteMock.mockResolvedValue({});
    const user = userEvent.setup();
    const { invalidateSpy } = renderRow();

    await user.click(screen.getByRole("button", { name: "Usuń z poprzednich: Anna Kowalska" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Ta osoba zejdzie z zespołu rekrutacji i nie wróci");
    await user.click(within(dialog).getByRole("button", { name: "Usuń z poprzednich" }));

    await waitFor(() =>
      expect(deleteMock).toHaveBeenCalledWith("/api/jobs/501/previous-recruiters/21"),
    );
    expect(toast.showSuccess).toHaveBeenCalledWith("Anna Kowalska: nie wróci przy P1.");
    expect(invalidateSpy).toHaveBeenCalled();
  });

  it("anulowanie niczego nie usuwa", async () => {
    const user = userEvent.setup();
    renderRow();

    await user.click(screen.getByRole("button", { name: "Usuń z poprzednich: Anna Kowalska" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(deleteMock).not.toHaveBeenCalled();
  });

  it("odmowa serwera idzie do toasta zdaniem z serwera", async () => {
    deleteMock.mockRejectedValue({
      response: { status: 404, data: { detail: "Tej osoby nie ma wśród poprzednich rekruterów." } },
    });
    const user = userEvent.setup();
    renderRow();

    await user.click(screen.getByRole("button", { name: "Usuń z poprzednich: Anna Kowalska" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Usuń z poprzednich",
      }),
    );

    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith(
        "Tej osoby nie ma wśród poprzednich rekruterów.",
      ),
    );
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: (...a: unknown[]) => toastSuccess(...a),
    showError: (...a: unknown[]) => toastError(...a),
  }),
}));

import { handoverView } from "@/components/v2/jobs/ClaimHandover";
import { PairOwnerLine } from "@/components/v2/jobs/PairOwnerLine";
import { useAuthStore } from "@/store/auth";

const NOW = new Date("2026-11-25T12:00:00Z");
const LATER = "2026-11-25T22:00:00Z";
const JOB = 789;

const PEOPLE = [
  { id: 7, name: "Ola Przykładowa", role: "recruiter", roles: ["recruiter"], is_active: true },
  { id: 8, name: "Wika Przykładowa", role: "recruiter", roles: ["recruiter"], is_active: true },
  { id: 9, name: "Ewa Nieaktywna", role: "recruiter", roles: ["recruiter"], is_active: false },
  { id: 10, name: "Dorota DL", role: "delivery_lead", roles: ["delivery_lead"], is_active: true },
];

const held = {
  candidate_id: 55,
  stage: "new",
  taken_by_user_id: 7,
  taken_by_name: "Ola Przykładowa",
  claim_user_id: 7,
  claim_user_name: "Ola Przykładowa",
  claim_until: LATER,
};

function renderAs(viewerId: number, item: Record<string, unknown> = held) {
  useAuthStore.setState({ user: { id: viewerId, name: "Patrzący", role: "recruiter", roles: ["recruiter"] } } as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PairOwnerLine item={item as never} jobId={JOB} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  get.mockResolvedValue({ data: PEOPLE });
  post.mockResolvedValue({ data: {} });
});

afterEach(() => {
  vi.useRealTimers();
  useAuthStore.setState({ user: null } as never);
  vi.clearAllMocks();
});

describe("handoverView — kto co widzi", () => {
  it("aktywna blokada: osoba z blokadą oddaje, reszta prosi", () => {
    expect(handoverView(held, 7, NOW)).toMatchObject({ holder: true, other: false, request: null });
    expect(handoverView(held, 8, NOW)).toMatchObject({ holder: false, other: true, askedByMe: false });
  });

  it("po upływie blokady nie ma czego oddawać ani o co prosić", () => {
    const expired = { ...held, claim_until: "2026-11-25T11:59:00Z", claim_request_user_id: 8 };
    expect(handoverView(expired, 7, NOW)).toEqual({ holder: false, other: false, request: null, askedByMe: false });
  });

  it("prośba: kto prosi i czy to ja", () => {
    const asked = { ...held, claim_request_user_id: 8, claim_request_user_name: "Wika Przykładowa", claim_request_reason: "znam ją" };
    expect(handoverView(asked, 7, NOW).request).toEqual({ userId: 8, name: "Wika Przykładowa", reason: "znam ją" });
    expect(handoverView(asked, 8, NOW).askedByMe).toBe(true);
    expect(handoverView(asked, 11, NOW).askedByMe).toBe(false);
  });
});

describe("Oddaj… i Zwolnij — osoba z blokadą", () => {
  it("oddaje wybranej osobie; na liście nie ma siebie, nieaktywnych ani osób bez roli rekrutera", async () => {
    const user = userEvent.setup();
    renderAs(7);
    await user.click(screen.getByTestId("claim-handover-give"));
    const select = await screen.findByLabelText("Komu");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
    expect(within(select).queryByText("Ola Przykładowa")).toBeNull();
    expect(within(select).queryByText("Ewa Nieaktywna")).toBeNull();
    expect(within(select).queryByText("Dorota DL")).toBeNull();
    await user.selectOptions(select, "8");
    await user.click(screen.getByRole("button", { name: "Oddaj — Wika" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/claim/handover", { candidate_id: 55, job_id: JOB, to_user_id: 8 }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Oddane — Wika Przykładowa ma osobę na 12 h.");
  });

  it("zwalnia dopiero po potwierdzeniu", async () => {
    const user = userEvent.setup();
    renderAs(7);
    await user.click(screen.getByTestId("claim-handover-release"));
    const dialog = await screen.findByRole("dialog");
    expect(post).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Zwolnij" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/pipeline/claim/release", { candidate_id: 55, job_id: JOB }));
  });

  it("błąd serwera mówi po polsku i nie udaje sukcesu", async () => {
    post.mockRejectedValueOnce({ response: { status: 409, data: { detail: "Blokada już wygasła — osobę może wziąć każdy z zespołu." } } });
    const user = userEvent.setup();
    renderAs(7);
    await user.click(screen.getByTestId("claim-handover-release"));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Zwolnij" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Blokada już wygasła — osobę może wziąć każdy z zespołu."));
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("prośba widoczna w pasku: „Oddaj — Wika” albo „Zostaw”", async () => {
    const user = userEvent.setup();
    renderAs(7, { ...held, claim_request_user_id: 8, claim_request_user_name: "Wika Przykładowa", claim_request_reason: "Znam ją od lat" });
    const banner = screen.getByTestId("claim-request-banner");
    expect(banner).toHaveTextContent("Wika Przykładowa prosi o tę osobę: „Znam ją od lat”");
    await user.click(within(banner).getByRole("button", { name: "Zostaw" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/claim/request/answer", { candidate_id: 55, job_id: JOB, accept: false }),
    );
    await user.click(within(banner).getByRole("button", { name: "Oddaj — Wika" }));
    await waitFor(() =>
      expect(post).toHaveBeenLastCalledWith("/api/pipeline/claim/request/answer", { candidate_id: 55, job_id: JOB, accept: true }),
    );
  });
});

describe("Poproś o oddanie — ktoś bez blokady", () => {
  it("wysyła prośbę z powodem; bez powodu przycisk nie działa", async () => {
    const user = userEvent.setup();
    renderAs(8);
    expect(screen.queryByTestId("claim-handover-give")).toBeNull();
    await user.click(screen.getByTestId("claim-handover-ask"));
    const dialog = await screen.findByRole("dialog");
    const send = within(dialog).getByRole("button", { name: "Wyślij prośbę" });
    expect(send).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox"), "Znam ją od lat");
    await user.click(send);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/claim/request", { candidate_id: 55, job_id: JOB, reason: "Znam ją od lat" }),
    );
  });

  it("moja prośba czeka; cudza prośba blokuje drugą", () => {
    const asked = { ...held, claim_request_user_id: 8, claim_request_user_name: "Wika Przykładowa" };
    const { unmount } = renderAs(8, asked);
    expect(screen.getByTestId("claim-handover-asked")).toHaveTextContent("Prośba wysłana");
    expect(screen.queryByTestId("claim-request-banner")).toBeNull();
    unmount();
    renderAs(11, asked);
    expect(screen.queryByTestId("claim-handover-ask")).toBeNull();
    expect(screen.getByText("· prosi Wika")).toBeInTheDocument();
  });

  it("wolna osoba i blokada po czasie: bez przycisków oddania", () => {
    renderAs(8, { ...held, claim_user_id: null, claim_until: null });
    expect(screen.queryByTestId("claim-handover-ask")).toBeNull();
    expect(screen.queryByTestId("claim-handover-give")).toBeNull();
  });
});

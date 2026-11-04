import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScreeningCallControl } from "@/components/v2/recruitment/ScreeningCallControl";
import { screeningCallsApi } from "@/lib/screening-call";
import { useAuthStore } from "@/store/auth";

const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

const saved = {
  event_id: 7,
  candidate_id: 1,
  job_id: 2,
  start_time: new Date(Date.now() + 3_600_000).toISOString(),
  status: "scheduled",
  outlook: "not_connected" as const,
};
const call = {
  event_id: 7,
  start_time: saved.start_time,
  note: "w pociągu",
  owner_id: 11,
  owner_name: "Właściciel",
};

function login(id: number, role = "recruiter") {
  useAuthStore.setState({ user: { id, role, roles: [role] } as never });
}

describe("ScreeningCallControl", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    showSuccess.mockClear();
    showError.mockClear();
    login(11);
  });

  it("umawia pierwszy podpowiedziany termin ze słowami kandydata", async () => {
    const book = vi.spyOn(screeningCallsApi, "book").mockResolvedValue(saved);
    wrap(<ScreeningCallControl candidateId={1} jobId={2} />);
    fireEvent.click(screen.getByRole("button", { name: "Umów telefon" }));
    fireEvent.change(screen.getByLabelText("Co powiedział kandydat"), {
      target: { value: "  w pociągu " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Umów" }));
    await waitFor(() => expect(book).toHaveBeenCalledTimes(1));
    const body = book.mock.calls[0][0];
    expect(body.candidate_id).toBe(1);
    expect(body.job_id).toBe(2);
    expect(body.note).toBe("w pociągu");
    expect(body.client_request_id.length).toBeGreaterThanOrEqual(16);
    await waitFor(() => expect(showSuccess).toHaveBeenCalled());
  });

  it("„Inny termin” bez daty nie pozwala zapisać", () => {
    wrap(<ScreeningCallControl candidateId={1} jobId={2} />);
    fireEvent.click(screen.getByRole("button", { name: "Umów telefon" }));
    fireEvent.click(screen.getByRole("button", { name: "Inny termin" }));
    expect(screen.getByRole("button", { name: "Umów" })).toBeDisabled();
  });

  it("pokazuje komunikat serwera, gdy zapis się nie uda", async () => {
    vi.spyOn(screeningCallsApi, "book").mockRejectedValue({
      response: { data: { detail: "Tę osobę prowadzi ktoś inny." } },
    });
    wrap(<ScreeningCallControl candidateId={1} jobId={2} />);
    fireEvent.click(screen.getByRole("button", { name: "Umów telefon" }));
    fireEvent.click(screen.getByRole("button", { name: "Umów" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
  });

  it("zapisany termin można przełożyć i odwołać", async () => {
    const reschedule = vi.spyOn(screeningCallsApi, "reschedule").mockResolvedValue(saved);
    const cancel = vi.spyOn(screeningCallsApi, "cancel").mockResolvedValue(saved);
    wrap(<ScreeningCallControl candidateId={1} jobId={2} call={call} />);
    expect(screen.getByText("„w pociągu”")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Odwołaj" }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith(7));

    fireEvent.click(screen.getByRole("button", { name: "Przełóż" }));
    expect(screen.getByLabelText("Co powiedział kandydat")).toHaveValue("w pociągu");
    // Bez wyboru nowego terminu nie ma czego zapisać.
    expect(screen.getAllByRole("button", { name: "Przełóż" }).at(-1)).toBeDisabled();
    fireEvent.click(screen.getByRole("group", { name: "Termin telefonu" }).querySelectorAll("button")[1]);
    fireEvent.click(screen.getAllByRole("button", { name: "Przełóż" }).at(-1)!);
    await waitFor(() => expect(reschedule).toHaveBeenCalledTimes(1));
    expect(reschedule.mock.calls[0][0]).toBe(7);
  });

  it("cudzy termin widać, ale bez przycisków", () => {
    login(99);
    wrap(<ScreeningCallControl candidateId={1} jobId={2} call={call} />);
    expect(screen.getByText("· Właściciel")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Odwołaj" })).toBeNull();
  });

  it("Delivery Lead zarządza cudzym terminem", () => {
    login(99, "delivery_lead");
    wrap(<ScreeningCallControl candidateId={1} jobId={2} call={call} />);
    expect(screen.getByRole("button", { name: "Odwołaj" })).toBeInTheDocument();
  });
});

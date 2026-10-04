import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showToast: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import { RateChangeBanner } from "@/components/v2/rate-change/RateChangeBanner";

const RATE = (n: number) => ({ amount: String(n), unit: "hourly", currency: "PLN", hourly: String(n), label: `${n} zł/h` });

function change(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    status: "requested",
    requires_decision: true,
    board_column: "cv_sent",
    previous: RATE(110),
    requested: RATE(130),
    agreed: null,
    source: "manual",
    source_label: "Panel osoby",
    reason: "conversation",
    reason_label: "Rozmowa z kandydatem",
    note: "ma drugą ofertę",
    negotiable: "maybe",
    created_at: "2026-10-04T10:00:00Z",
    created_by_name: "Sandra",
    negotiator_id: null,
    negotiator_name: null,
    negotiation_target_hourly: null,
    negotiation_due: null,
    outcome: null,
    outcome_note: null,
    decision: null,
    decided_at: null,
    decided_by_name: null,
    can_record_outcome: false,
    ...overrides,
  };
}

function view(overrides: Record<string, unknown> = {}, c = change()) {
  return {
    candidate_id: 5,
    job_id: 9,
    current: RATE(130),
    board_column: "cv_sent",
    notifies: true,
    cv_at_client: true,
    client_rate: RATE(150),
    changes: [c],
    can_manage: true,
    can_decide: true,
    negotiator_options: [
      { id: 21, name: "Anna DL", role_label: "Delivery Lead" },
      { id: 22, name: "Olaf HoR", role_label: "Head of Recruitment" },
    ],
    ...overrides,
  };
}

function renderBanner(onWithdraw?: () => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RateChangeBanner candidateId={5} jobId={9} onWithdraw={onWithdraw} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  Object.values(mocks.toast).forEach((fn) => fn.mockReset());
});

describe("RateChangeBanner", () => {
  it("DL widzi sprawę i wszystkie akcje; „Zostawiam” zapisuje decyzję", async () => {
    mocks.get.mockResolvedValue({ data: view() });
    mocks.post.mockResolvedValue({ data: change({ status: "closed", decision: "keep_client" }) });
    renderBanner();
    expect(await screen.findByTestId("rate-change-banner")).toHaveTextContent(
      "Kandydat chce 130 zł/h (było 110 zł/h) · CV jest u klienta — czeka na decyzję DL",
    );
    expect(screen.getByRole("button", { name: "Zleć negocjację" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zostawiam stawkę do klienta" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/rate-changes/7/decision", { decision: "keep_client" }),
    );
  });

  it("rekruter bez uprawnień widzi tylko stan, bez przycisków", async () => {
    mocks.get.mockResolvedValue({ data: view({ can_manage: false, can_decide: false }) });
    renderBanner();
    await screen.findByTestId("rate-change-banner");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("„Zleć negocjację” wysyła osobę, cel i termin", async () => {
    mocks.get.mockResolvedValue({ data: view() });
    mocks.post.mockResolvedValue({ data: change({ status: "negotiating" }) });
    renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: "Zleć negocjację" }));
    fireEvent.change(screen.getByLabelText("Kto porozmawia z kandydatem"), { target: { value: "22" } });
    fireEvent.change(screen.getByLabelText("Cel (zł/h, opcjonalnie)"), { target: { value: "120" } });
    fireEvent.change(screen.getByLabelText("Do kiedy (opcjonalnie)"), { target: { value: "2026-10-08" } });
    fireEvent.click(screen.getByRole("button", { name: "Zleć" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/rate-changes/7/negotiation", {
        negotiator_id: 22,
        target_hourly: "120",
        due: "2026-10-08",
      }),
    );
  });

  it("negocjator zapisuje niższą stawkę", async () => {
    const c = change({ status: "negotiating", negotiator_name: "Olaf HoR", negotiation_due: "2026-10-08", can_record_outcome: true });
    mocks.get.mockResolvedValue({ data: view({ can_manage: false, can_decide: false }, c) });
    mocks.post.mockResolvedValue({ data: change({ status: "agreed" }) });
    renderBanner();
    expect(await screen.findByTestId("rate-change-banner")).toHaveTextContent("w negocjacji — rozmawia Olaf HoR do 08.10");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz wynik rozmowy" }));
    fireEvent.change(screen.getByLabelText("Ustalona stawka B2B netto (zł/h)"), { target: { value: "120" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz wynik" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/rate-changes/7/outcome", {
        outcome: "lower",
        agreed_amount: "120",
        note: null,
      }),
    );
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith(
      "Wynik zapisany. Delivery Lead zdecyduje o stawce do klienta.",
    );
  });

  it("„Podnoszę” podpowiada stawkę do klienta powiększoną o różnicę", async () => {
    mocks.get.mockResolvedValue({ data: view() });
    mocks.post.mockResolvedValue({ data: change({ status: "closed" }) });
    renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: "Podnoszę stawkę do klienta" }));
    expect(screen.getByLabelText("Stawka do klienta (zł/h)")).toHaveValue("170");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/rate-changes/7/decision", {
        decision: "raise_client",
        client_rate: { amount: "170", unit: "hourly" },
      }),
    );
  });

  it("„Wycofujemy” zapisuje decyzję i otwiera odrzucenie karty", async () => {
    const onWithdraw = vi.fn();
    mocks.get.mockResolvedValue({ data: view() });
    mocks.post.mockResolvedValue({ data: change({ status: "closed", decision: "withdraw" }) });
    renderBanner(onWithdraw);
    fireEvent.click(await screen.findByRole("button", { name: "Wycofujemy kandydata" }));
    await waitFor(() => expect(onWithdraw).toHaveBeenCalled());
  });

  it("bez otwartej sprawy nic nie pokazuje", async () => {
    mocks.get.mockResolvedValue({ data: view({}, change({ status: "closed" })) });
    const { container } = renderBanner();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

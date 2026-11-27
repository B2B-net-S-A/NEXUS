import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { B2BGeneratedContractRow, B2BKrzState } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  recordKrz: vi.fn(),
  decideKrz: vi.fn(),
  showSuccess: vi.fn(),
  showInfo: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showInfo: mocks.showInfo }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    b2bGeneratorApi: {
      ...actual.b2bGeneratorApi,
      recordKrz: (...a: unknown[]) => mocks.recordKrz(...a),
      decideKrz: (...a: unknown[]) => mocks.decideKrz(...a),
    },
  };
});

import { KrzGate } from "../KrzGate";

const STATE: B2BKrzState = {
  required: true,
  result: null,
  entry_kind: null,
  entry_label: null,
  entry_note: null,
  checked_at: null,
  checked_by_name: null,
  decision: null,
  decision_reason: null,
  decided_at: null,
  decided_by_name: null,
  nip_changed: false,
  block_reason: "Najpierw sprawdź Partnera w Krajowym Rejestrze Zadłużonych.",
  decider_names: ["Anna Lead"],
  can_record: true,
  can_decide: false,
};

function row(krz: Partial<B2BKrzState>): B2BGeneratedContractRow {
  return {
    id: 9,
    contract_number: "1591/2026",
    partner_nip: "5214188498",
    partner_name: "Ewa Przykładowa",
    partner_display_name: "Ewa Przykładowa IT",
    contract_status: "in_progress",
    krz: { ...STATE, ...krz },
  } as unknown as B2BGeneratedContractRow;
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("KrzGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.recordKrz.mockResolvedValue({});
    mocks.decideKrz.mockResolvedValue({});
  });

  it("niesprawdzona umowa: plakietka i „Sprawdź w KRZ”, PESEL nie idzie do API", async () => {
    const user = userEvent.setup();
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    wrap(<KrzGate row={row({})} />);
    expect(screen.getByTestId("krz-badge")).toHaveTextContent("KRZ: nie sprawdzono");

    await user.click(screen.getByRole("button", { name: "Sprawdź w KRZ" }));
    await user.click(screen.getByRole("button", { name: /Otwórz KRZ: NIP 5214188498/ }));
    expect(open).toHaveBeenCalledWith(expect.stringContaining("krz.ms.gov.pl"), "_blank", "noopener,noreferrer");

    await user.type(screen.getByPlaceholderText("PESEL Partnera"), "44051401359");
    const save = screen.getByRole("button", { name: "Zapisz wynik" });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "Brak wpisów" }));
    await user.click(save);

    await waitFor(() => expect(mocks.recordKrz).toHaveBeenCalledWith(9, { result: "clear" }));
    expect(JSON.stringify(mocks.recordKrz.mock.calls)).not.toContain("44051401359");
    open.mockRestore();
  });

  it("wpis bez rodzaju nie da się zapisać", async () => {
    const user = userEvent.setup();
    wrap(<KrzGate row={row({})} />);
    await user.click(screen.getByRole("button", { name: "Sprawdź w KRZ" }));
    await user.click(screen.getByRole("radio", { name: "Jest wpis" }));
    expect(screen.getByRole("button", { name: "Zapisz wynik" })).toBeDisabled();
  });

  it("autor widzi, na kogo czeka wpis, a nie przycisk decyzji", () => {
    wrap(<KrzGate row={row({ result: "entry", entry_label: "Upadłość" })} />);
    expect(screen.getByTestId("krz-badge")).toHaveTextContent("KRZ: wpis, decyzja DL");
    expect(screen.getByText("Czeka na decyzję: Anna Lead.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zdecyduj o wpisie" })).toBeNull();
  });

  it("Delivery Lead decyduje z uzasadnieniem", async () => {
    const user = userEvent.setup();
    wrap(
      <KrzGate
        row={row({ result: "entry", entry_label: "Upadłość", can_decide: true, can_record: false })}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Zdecyduj o wpisie" }));
    const allow = screen.getByRole("button", { name: "Dopuść do podpisu" });
    expect(allow).toBeDisabled();
    await user.type(screen.getByLabelText("Uzasadnienie"), "spłacone w 2025");
    await user.click(allow);
    await waitFor(() =>
      expect(mocks.decideKrz).toHaveBeenCalledWith(9, {
        decision: "allowed",
        reason: "spłacone w 2025",
      }),
    );
  });

  it("wiersz poza sprawdzeniem nic nie pokazuje", () => {
    const { container } = wrap(
      <KrzGate row={row({ required: false, result: null, block_reason: null })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

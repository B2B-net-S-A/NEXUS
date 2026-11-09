/**
 * Karta „Premia 200%”: umowy osoby z dniem podpisu, jego źródłem i „Popraw datę”
 * (decyzja Artura 06.11.2026: umowa oznaczona 30.10, podpis 02.11). Dane fikcyjne.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DoubleBonusContract, DoubleBonusMonth } from "@/lib/api/hr-payroll";

import { DoubleBonusCard } from "../DoubleBonusCard";
import { signedSourceInfo } from "../double-bonus-format";

const mocks = vi.hoisted(() => ({
  correct: vi.fn(),
  showToast: vi.fn(),
  month: null as unknown as DoubleBonusMonth,
}));

vi.mock("@/lib/api/hr-payroll", async (original) => ({
  ...(await original<typeof import("@/lib/api/hr-payroll")>()),
  useDoubleBonusMonth: () => ({ data: mocks.month, isSuccess: true, isError: false }),
  useSettleDoubleBonus: () => ({ mutate: vi.fn(), isPending: false }),
  useCorrectSignedOn: () => ({ mutate: mocks.correct, isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.showToast }) }));

const clicked: DoubleBonusContract = {
  contract_id: 501,
  label: "Piotr Przykładowy (Bank Przykładowy)",
  signed_on: "2026-10-30",
  signed_source: "signed",
  margin_per_hour: "40.00",
  agreement: {
    generated_contract_id: 1555,
    contract_number: "1555/2026",
    signed_on_source: null,
    signed_on_reason: null,
    set_by_name: null,
    marked_by_name: "Delivery Lead Przykładowy",
    marked_at: "2026-10-30T13:00:00Z",
    consultant_signed_at: null,
    has_signed_file: false,
  },
};

const fromPdf: DoubleBonusContract = {
  ...clicked,
  contract_id: 729,
  label: "Anna Przykładowa (Bank Drugi)",
  signed_on: "2026-11-02",
  signed_source: "pdf",
  agreement: {
    ...clicked.agreement!,
    generated_contract_id: 1556,
    signed_on_source: "pdf",
    consultant_signed_at: "2026-11-02T06:32:00Z",
    has_signed_file: true,
  },
};

const moment = (iso: string) => `M(${iso})`;

describe("signedSourceInfo", () => {
  it("data z kliknięcia bez pliku dostaje „sprawdź”", () => {
    expect(signedSourceInfo(clicked, moment)).toEqual({
      text: "wpisany przy oznaczeniu przez Delivery Lead Przykładowy · bez pliku",
      tag: "sprawdź",
      needsCheck: true,
    });
  });

  it("z pliku podaje chwilę podpisu konsultanta", () => {
    expect(signedSourceInfo(fromPdf, moment)).toEqual({
      text: "z pliku · podpis M(2026-11-02T06:32:00Z)",
      tag: "z podpisu",
      needsCheck: false,
    });
  });

  it("ręcznie podaje kto i powód; e-podpis i kontrakt bez umowy", () => {
    const manual: DoubleBonusContract = {
      ...clicked,
      signed_source: "manual",
      agreement: { ...clicked.agreement!, set_by_name: "Płace Przykładowe", signed_on_reason: "podpis 02.11" },
    };
    expect(signedSourceInfo(manual, moment).text).toBe("ręcznie przez Płace Przykładowe · podpis 02.11");
    expect(signedSourceInfo({ ...clicked, signed_source: "esign" }, moment).text).toBe("e-podpis w NEXUSIE");
    expect(
      signedSourceInfo({ ...clicked, signed_source: "created", agreement: null }, moment).needsCheck,
    ).toBe(true);
  });
});

describe("DoubleBonusCard — umowy i poprawka daty", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.month = {
      year: 2026,
      month: 10,
      in_program: true,
      final: true,
      stored: null,
      recruiters: [],
      dls: [
        {
          user_id: 30,
          name: "Delivery Lead Przykładowy",
          kind: "dl",
          placements: 2,
          average_margin: "40.00",
          missing_margins: 0,
          excluded: null,
          qualified: false,
          contracts: [clicked, { ...fromPdf, agreement: null, signed_source: "created" }],
        },
      ],
    } as DoubleBonusMonth;
  });

  it("pokazuje umowy z dniem i źródłem, „Popraw datę” tylko przy umowie z Generatora", () => {
    render(<DoubleBonusCard year={2026} month={10} open />);
    const list = screen.getByRole("list", { name: "Umowy: Delivery Lead Przykładowy" });
    const items = within(list).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("podpis 30.10.2026");
    expect(items[0]).toHaveTextContent("bez pliku");
    expect(within(items[0]).getByText("sprawdź")).toBeInTheDocument();
    expect(within(items[0]).getByRole("button", { name: "Popraw datę" })).toBeInTheDocument();
    expect(within(items[1]).queryByRole("button", { name: "Popraw datę" })).toBeNull();
  });

  it("poprawka wymaga powodu i wysyła datę z powodem", async () => {
    mocks.correct.mockImplementation((_input, options) =>
      options.onSuccess({
        generated_contract_id: 1555,
        contract_id: 501,
        signed_on: "2026-11-02",
        previous_signed_on: "2026-10-30",
        settle_months: ["2026-10"],
      }),
    );
    render(<DoubleBonusCard year={2026} month={10} open />);
    fireEvent.click(screen.getByRole("button", { name: "Popraw datę" }));
    const dialog = await screen.findByRole("dialog");
    const save = within(dialog).getByRole("button", { name: "Zapisz datę" });
    fireEvent.change(within(dialog).getByLabelText("Data podpisu konsultanta"), {
      target: { value: "2026-11-02" },
    });
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Powód"), {
      target: { value: "podpis konsultanta w pliku 02.11 07:32" },
    });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    expect(mocks.correct).toHaveBeenCalledWith(
      {
        generatedContractId: 1555,
        signedOn: "2026-11-02",
        reason: "podpis konsultanta w pliku 02.11 07:32",
      },
      expect.anything(),
    );
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        "Data podpisu poprawiona na 02.11.2026. Przelicz wynik: październik 2026.",
        "success",
      ),
    );
  });
});

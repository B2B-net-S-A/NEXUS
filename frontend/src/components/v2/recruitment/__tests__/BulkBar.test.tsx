import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  downloadBulkCvs: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/bulk-cv-download", () => ({
  BulkCvDownloadError: class extends Error {},
  downloadBulkCvs: mocks.downloadBulkCvs,
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

import { BulkBar, bulkSendCvBlockedReason } from "@/components/v2/recruitment/BulkBar";
import { buildProcessRows } from "@/components/v2/recruitment/person-rows";
import type { ProposalPersonRow } from "@/components/v2/recruitment/types";
import type { PipelineMoveControls } from "@/hooks/usePipelineMove";

import { item, template } from "./recruitment-fixtures";

const columns = template({ 3: [item(1), item(2)], 1: [item(3)] });
const rows = buildProcessRows(columns);
const verified = rows.filter((r) => r.group === "verification");

function moveControls(over: Partial<PipelineMoveControls> = {}): PipelineMoveControls {
  return {
    requestMove: vi.fn(),
    requestBulkMove: vi.fn().mockResolvedValue(undefined),
    requestReject: vi.fn(),
    isMoving: false,
    dialogs: null,
    ...over,
  };
}

const proposal = (id: number): ProposalPersonRow => ({
  kind: "proposal", key: `prop:${id}`, candidateId: id, fullName: `Osoba ${id}`, rateLabel: null,
  availabilityLabel: null, fitScore: null, warnings: [], sources: ["full_base"], reason: null,
  isNew: false, previouslyDismissed: false, runId: null,
});

beforeEach(() => vi.clearAllMocks());

describe("BulkBar — osoby w procesie", () => {
  it("bez zaznaczenia nie renderuje nic", () => {
    const { container } = render(<BulkBar rows={[]} columns={columns} move={moveControls()} onClear={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("„Wyślij CV do klienta” aktywne tylko gdy KAŻDA zaznaczona osoba jest zweryfikowana", async () => {
    const onBulkSendCv = vi.fn();
    const { rerender } = render(
      <BulkBar rows={rows} columns={columns} move={moveControls()} onClear={vi.fn()} onBulkSendCv={onBulkSendCv} />,
    );
    expect(screen.getByText("Zaznaczono 3")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Wyślij CV do klienta" });
    expect(send).toBeDisabled();
    expect(send).toHaveAttribute("title", expect.stringContaining("1 z zaznaczonych"));

    rerender(
      <BulkBar rows={verified} columns={columns} move={moveControls()} onClear={vi.fn()} onBulkSendCv={onBulkSendCv} />,
    );
    const enabled = screen.getByRole("button", { name: "Wyślij CV do klienta" });
    expect(enabled).toBeEnabled();
    await userEvent.click(enabled);
    expect(onBulkSendCv).toHaveBeenCalledWith(verified);
  });

  it("powód blokady wysyłki CV", () => {
    expect(bulkSendCvBlockedReason(verified)).toBeNull();
    expect(bulkSendCvBlockedReason(rows.filter((r) => r.group === "intake"))).toMatch(/żadna z zaznaczonych/);
  });

  it("„Przenieś na etap…” — cele bez terminali, ruch przez requestBulkMove z czyszczeniem zaznaczenia", async () => {
    const move = moveControls();
    const onClear = vi.fn();
    render(<BulkBar rows={verified} columns={columns} move={move} onClear={onClear} />);
    await userEvent.click(screen.getByRole("button", { name: /Przenieś na etap/ }));
    const targets = (await screen.findAllByRole("menuitem")).map((m) => m.textContent);
    expect(targets).toContain("CV Wysłane");
    expect(targets).not.toContain("Zatrudniony");
    expect(targets).not.toContain("Odrzucony");
    await userEvent.click(screen.getByRole("menuitem", { name: "CV Wysłane" }));
    await waitFor(() => expect(move.requestBulkMove).toHaveBeenCalled());
    const [items, target, options] = (move.requestBulkMove as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(items).toEqual(verified.map((r) => r.item));
    expect(target.stage).toBe("cv_sent");
    options.onHandled();
    expect(onClear).toHaveBeenCalled();
  });

  it("„Odrzuć” idzie przez requestReject; trwający ruch blokuje akcje", async () => {
    const move = moveControls();
    const { rerender } = render(<BulkBar rows={verified} columns={columns} move={move} onClear={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Odrzuć" }));
    expect(move.requestReject).toHaveBeenCalledWith(verified.map((r) => r.item));
    rerender(<BulkBar rows={verified} columns={columns} move={moveControls({ isMoving: true })} onClear={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Odrzuć" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Przenieś na etap/ })).toBeDisabled();
  });

  it("„CV (ZIP)” pobiera CV zaznaczonych i mówi, ile pominięto", async () => {
    mocks.downloadBulkCvs.mockResolvedValue({ includedCount: 1, skippedCount: 1 });
    render(<BulkBar rows={verified} columns={columns} move={moveControls()} onClear={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "CV (ZIP)" }));
    expect(mocks.downloadBulkCvs).toHaveBeenCalledWith([1, 2]);
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalledWith("Pobrano CV: 1. Bez pliku CV: 1."));
  });

  it("„Wyczyść” czyści zaznaczenie", async () => {
    const onClear = vi.fn();
    render(<BulkBar rows={verified} columns={columns} move={moveControls()} onClear={onClear} />);
    await userEvent.click(screen.getByRole("button", { name: "Wyczyść" }));
    expect(onClear).toHaveBeenCalled();
  });
});

describe("BulkBar — propozycje", () => {
  it("Dodaj / Pomiń / Porównaj; porównanie przyjmuje 2–3 osoby", async () => {
    const onAdd = vi.fn();
    const onDismiss = vi.fn();
    const two = [proposal(7), proposal(8)];
    const { rerender } = render(
      <BulkBar rows={two} columns={columns} move={moveControls()} onClear={vi.fn()} onAddProposals={onAdd} onDismissProposals={onDismiss} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Dodaj do rekrutacji" }));
    expect(onAdd).toHaveBeenCalledWith(two);
    await userEvent.click(screen.getByRole("button", { name: "Pomiń" }));
    expect(onDismiss).toHaveBeenCalledWith(two);
    expect(screen.getByRole("link", { name: "Porównaj" }).getAttribute("href")).toMatch(
      /^\/candidates\/compare\?.*ids=7%2C8/,
    );
    expect(screen.queryByRole("button", { name: /Przenieś na etap/ })).not.toBeInTheDocument();

    rerender(
      <BulkBar rows={[1, 2, 3, 4].map(proposal)} columns={columns} move={moveControls()} onClear={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Porównaj" })).toBeDisabled();
  });
});

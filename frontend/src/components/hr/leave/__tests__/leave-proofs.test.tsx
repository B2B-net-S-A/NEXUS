/**
 * Załącznik do wniosku urlopowego: reguły pliku, „Załącznik ✓” u przełożonego
 * (bez pobrania — D6), pobranie u Kadr i „Dołącz plik” w „Moje nieobecności”.
 * Hooki API zamockowane, dane fikcyjne.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { LeaveProof, LeaveRequestRow } from "@/lib/api/hr-leave";

import { ApproverProofNote, MyProofsCell } from "../LeaveProofs";
import { canAttachMore, proofHint, proofProblem, proofSummary } from "../leave-proofs";

const mocks = vi.hoisted(() => ({
  attach: vi.fn(),
  remove: vi.fn(),
  download: vi.fn(() => Promise.resolve()),
}));

vi.mock("@/lib/api/hr-leave", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr-leave")>()),
  useAttachLeaveProof: () => ({ mutate: mocks.attach, isPending: false }),
  useRemoveLeaveProof: () => ({ mutate: mocks.remove, isPending: false }),
  downloadLeaveProof: mocks.download,
}));

const PROOF: LeaveProof = {
  id: 11,
  file_name: "akt-urodzenia.pdf",
  mime: "application/pdf",
  size_bytes: 1200,
  created_at: "2026-11-02T10:00:00+01:00",
  can_remove: true,
};

const row = (overrides: Partial<LeaveRequestRow> = {}): LeaveRequestRow => ({
  id: "r1",
  user_id: 1,
  user_name: "Anna Przykładowa",
  leave_type: "occasional",
  leave_type_label: "Urlop okolicznościowy",
  status: "pending",
  start_date: "2026-11-02",
  end_date: "2026-11-03",
  half_day: null,
  days_total: "2.0",
  paid_days: "2.0",
  unpaid_days: "0.0",
  note: null,
  substitute_user_id: null,
  substitute_name: null,
  forward_mail_consent: false,
  oof_internal_message: null,
  oof_external_message: null,
  decided_by_name: null,
  decided_at: null,
  decision_note: null,
  source: "self",
  created_at: null,
  can_cancel: true,
  proof_count: 0,
  proofs: [],
  can_add_proof: true,
  ...overrides,
});

function renderWithToast(node: React.ReactNode) {
  return render(<ToastProvider>{node}</ToastProvider>);
}

beforeEach(() => {
  mocks.attach.mockReset();
  mocks.remove.mockReset();
  mocks.download.mockClear();
});

describe("reguły załącznika", () => {
  it("podpowiedź tylko przy okolicznościowym, opiece nad dzieckiem i krwiodawstwie", () => {
    expect(proofHint("occasional")).toMatch(/akt ślubu/);
    expect(proofHint("childcare")).toMatch(/dziecka/);
    expect(proofHint("blood_donation")).toMatch(/krwiodawstwa/);
    expect(proofHint("sick_leave")).toBeNull();
    expect(proofHint("vacation")).toBeNull();
  });

  it("PDF, JPG, PNG do 5 MB — reszta z komunikatem przed wysłaniem", () => {
    const file = (name: string, size: number) =>
      new File([new Uint8Array(size)], name, { type: "application/octet-stream" });
    expect(proofProblem(file("akt.PDF", 10))).toBeNull();
    expect(proofProblem(file("skan.jpeg", 10))).toBeNull();
    expect(proofProblem(file("akt.docx", 10))).toBe("Dołącz PDF albo zdjęcie (JPG, PNG).");
    expect(proofProblem(file("pusty.pdf", 0))).toBe("Plik jest pusty.");
    expect(proofProblem(file("duzy.png", 5 * 1024 * 1024 + 1))).toBe(
      "Załącznik może mieć najwyżej 5 MB.",
    );
  });

  it("„Załącznik ✓” z liczbą; nic przy braku albo ukrytej liczbie", () => {
    expect(proofSummary({ proof_count: 1 })).toBe("Załącznik ✓");
    expect(proofSummary({ proof_count: 3 })).toBe("3 załączniki ✓");
    expect(proofSummary({ proof_count: 0 })).toBeNull();
    expect(proofSummary({ proof_count: null })).toBeNull();
    expect(canAttachMore(row({ proof_count: 5 }))).toBe(false);
    expect(canAttachMore(row({ can_add_proof: false }))).toBe(false);
  });
});

describe("akceptacje", () => {
  it("przełożony: „Załącznik ✓” bez nazwy pliku i bez pobrania (D6)", () => {
    renderWithToast(<ApproverProofNote row={row({ proof_count: 1, proofs: null })} />);
    expect(screen.getByText("Załącznik ✓")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText(/akt-urodzenia/)).toBeNull();
  });

  it("Kadry: nazwa pliku pobiera go ścieżką akceptacji", async () => {
    const user = userEvent.setup();
    const proof = { ...PROOF, can_remove: false };
    renderWithToast(<ApproverProofNote row={row({ proof_count: 1, proofs: [proof] })} />);
    await user.click(screen.getByRole("button", { name: "akt-urodzenia.pdf" }));
    expect(mocks.download).toHaveBeenCalledWith("r1", proof, "team");
  });

  it("bez załącznika nic nie rysuje", () => {
    renderWithToast(<ApproverProofNote row={row()} />);
    expect(screen.queryByText(/Załącznik/)).toBeNull();
  });
});

describe("„Moje nieobecności”", () => {
  it("„Dołącz plik” wysyła wybrany plik do tego wniosku", async () => {
    const user = userEvent.setup();
    renderWithToast(<MyProofsCell row={row()} />);
    const file = new File(["%PDF-1.4"], "zaswiadczenie.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Dołącz plik do wniosku"), file);
    expect(mocks.attach).toHaveBeenCalledTimes(1);
    expect(mocks.attach.mock.calls[0][0]).toEqual({ id: "r1", file });
  });

  it("za duży plik nie wychodzi z przeglądarki", async () => {
    const user = userEvent.setup();
    renderWithToast(<MyProofsCell row={row()} />);
    const big = new File([new Uint8Array(5 * 1024 * 1024 + 1)], "duzy.pdf", {
      type: "application/pdf",
    });
    await user.upload(screen.getByLabelText("Dołącz plik do wniosku"), big);
    expect(mocks.attach).not.toHaveBeenCalled();
    expect(await screen.findByText("Załącznik może mieć najwyżej 5 MB.")).toBeInTheDocument();
  });

  it("własny plik: pobranie ścieżką osoby i usunięcie po potwierdzeniu", async () => {
    const user = userEvent.setup();
    renderWithToast(<MyProofsCell row={row({ proof_count: 1, proofs: [PROOF] })} />);
    await user.click(screen.getByRole("button", { name: "akt-urodzenia.pdf" }));
    expect(mocks.download).toHaveBeenCalledWith("r1", PROOF, "own");

    await user.click(screen.getByRole("button", { name: "Usuń akt-urodzenia.pdf" }));
    await user.click(await screen.findByRole("button", { name: "Usuń" }));
    expect(mocks.remove).toHaveBeenCalledWith(
      { id: "r1", proofId: 11 },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("anulowany wniosek bez plików: kreska, bez „Dołącz plik”", () => {
    renderWithToast(<MyProofsCell row={row({ status: "cancelled", can_add_proof: false })} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByLabelText("Dołącz plik do wniosku")).toBeNull();
  });
});

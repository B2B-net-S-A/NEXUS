import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { RequirementVerificationDialog } from "./RequirementVerificationDialog";
import type { RequirementVerificationData } from "@/lib/requirement-verifications-api";
const mocks = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn() }));
vi.mock("@/lib/requirement-verifications-api", () => ({ requirementVerificationsApi: mocks }));
const data: RequirementVerificationData = {
  requirements: { version: 1, reviewed: true, missing_evidence_policy: "review", all_of: [{ any_of: ["python", "java"], level: "must", source: "manual", evidence: "" }] },
  candidate_version: "v1", requirements_fingerprint: "a".repeat(64), verifications: [],
};
beforeEach(() => { mocks.read.mockReset(); mocks.save.mockReset(); mocks.read.mockResolvedValue(data); mocks.save.mockResolvedValue({ id: 9, candidate_version: "v2", status: "not_met" }); });
async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Zweryfikuj wymaganie" }));
  await screen.findByRole("combobox", { name: "Wymaganie" });
}
function fill() {
  fireEvent.change(screen.getByLabelText("Wymaganie"), { target: { value: "0" } });
  fireEvent.change(screen.getByLabelText("Wynik weryfikacji"), { target: { value: "not_met" } });
  fireEvent.change(screen.getByLabelText("Dowód / uzasadnienie"), { target: { value: "Test praktyczny" } });
  fireEvent.change(screen.getByLabelText("Kontekst i wymagany poziom"), { target: { value: "Samodzielny backend" } });
  fireEvent.change(screen.getByLabelText("Data weryfikacji"), { target: { value: "2020-01-02T12:00" } });
}
test("only explicit submit writes current context and selected OR group", async () => {
  const saved = vi.fn();
  render(<RequirementVerificationDialog jobId={7} candidateId={1} candidateName="Anna" onSaved={saved} />);
  expect(mocks.read).not.toHaveBeenCalled();
  await open();
  expect(screen.getByRole("button", { name: "Zapisz weryfikację" })).toBeDisabled();
  expect(mocks.save).not.toHaveBeenCalled(); fill();
  fireEvent.click(screen.getByRole("button", { name: "Zapisz weryfikację" }));
  await screen.findByText(/Weryfikacja zapisana/);
  expect(mocks.save).toHaveBeenCalledWith(7, 1, {
    requirement_index: 0, requirements_fingerprint: data.requirements_fingerprint,
    candidate_version: "v1", status: "not_met", evidence: "Test praktyczny", usage_context: "Samodzielny backend",
    verified_at: new Date("2020-01-02T12:00").toISOString(),
  });
  expect(saved).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("Dowód / uzasadnienie")).toHaveValue("");
});
test("version conflict retains proof and requires refreshed requirement selection", async () => {
  mocks.save.mockRejectedValueOnce({ response: { status: 409, data: { detail: "Profil zmienił się" } } });
  mocks.read.mockResolvedValueOnce(data).mockResolvedValue({ ...data, candidate_version: "v2" });
  render(<RequirementVerificationDialog jobId={7} candidateId={1} candidateName="Anna" onSaved={vi.fn()} />);
  await open(); fill();
  fireEvent.click(screen.getByRole("button", { name: "Zapisz weryfikację" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Dowód / uzasadnienie")).toHaveValue("Test praktyczny");
  expect(screen.getByRole("button", { name: "Zapisz weryfikację" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Odśwież dane" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(screen.getByLabelText("Wymaganie")).toHaveValue("");
  expect(screen.getByLabelText("Dowód / uzasadnienie")).toHaveValue("Test praktyczny");
  fireEvent.change(screen.getByLabelText("Wymaganie"), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz weryfikację" }));
  await waitFor(() => expect(mocks.save).toHaveBeenCalledTimes(2));
  expect(mocks.save.mock.calls[1][2].candidate_version).toBe("v2");
});
test("failed read does not display an editable fabricated form", async () => {
  mocks.read.mockRejectedValueOnce(new Error("Brak dostępu"));
  render(<RequirementVerificationDialog jobId={7} candidateId={1} candidateName="Anna" onSaved={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Zweryfikuj wymaganie" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "Zapisz weryfikację" })).not.toBeInTheDocument();
  expect(mocks.save).not.toHaveBeenCalled();
});
test("late response from another candidate cannot replace the active form", async () => {
  let resolveOld!: (value: RequirementVerificationData) => void;
  mocks.read.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; })).mockResolvedValue(data);
  const view = render(<RequirementVerificationDialog jobId={7} candidateId={1} candidateName="Anna" onSaved={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Zweryfikuj wymaganie" }));
  view.rerender(<RequirementVerificationDialog jobId={7} candidateId={2} candidateName="Jan" onSaved={vi.fn()} />);
  await screen.findByLabelText("Wymaganie");
  await act(async () => { resolveOld({ ...data, candidate_version: "wrong-person" }); });
  fill(); fireEvent.click(screen.getByRole("button", { name: "Zapisz weryfikację" }));
  await waitFor(() => expect(mocks.save).toHaveBeenCalled());
  expect(mocks.save.mock.calls[0][0]).toBe(7);
  expect(mocks.save.mock.calls[0][1]).toBe(2);
  expect(mocks.save.mock.calls[0][2].candidate_version).toBe("v1");
});

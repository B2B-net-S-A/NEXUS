import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChampionImportButton, ChampionImportReview } from "../ChampionIntake";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), api: { post } }));
const profile = (rate: number): ChampionProfile => ({ ...structuredClone(EMPTY_CHAMPION_PROFILE), basics: { ...EMPTY_CHAMPION_PROFILE.basics, role_name: "Java Developer", rate_value: rate }, intake: { policy_version: 1, template_version: "4.0", unresolved: {} } });

beforeEach(() => {
  post.mockReset();
  post.mockImplementation(async (_url, body) => ({ data: _url.endsWith("validate") ? { champion_profile: body.profile } : { champion_profile: body.profile } }));
});

describe("Champion import review", () => {
  it("waits for apply and preserves nonempty current data by default", async () => {
    const onApply = vi.fn();
    render(<ChampionImportReview initial={{ champion_profile: profile(150) }} current={profile(100)} jobId={7} fingerprint={"a".repeat(64)} onApply={onApply} onClose={() => {}} />);
    expect(post).not.toHaveBeenCalled(); expect(onApply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(post.mock.calls[0][1].profile.basics.rate_value).toBe("100");
    expect(post.mock.calls[1][0]).toBe("/api/jobs/7/champion-profile/apply-import");
    expect(post.mock.calls[1][1].expected_fingerprint).toBe("a".repeat(64));
    expect(post.mock.calls[1][1].profile.intake.template_version).toBe("4.0");
    expect(post.mock.calls[1][1].sync_fields).toEqual([]);
  });

  it("shows the ambiguous source and lets the user replace it", async () => {
    const incoming = profile(150);
    incoming.basics.rate_value = null;
    incoming.intake!.unresolved["basics.rate_value"] = "100–150 EUR/h";
    const onApply = vi.fn();
    render(<ChampionImportReview initial={{ champion_profile: incoming }} onApply={onApply} onClose={() => {}} />);
    expect(screen.getByLabelText("Maksymalna stawka PLN/h")).toHaveValue("100–150 EUR/h");
    fireEvent.change(screen.getByLabelText("Maksymalna stawka PLN/h"), { target: { value: "150" } });
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(post.mock.calls[0][1].profile.basics.rate_value).toBe("150");
    expect(post.mock.calls[0][1].profile.intake.unresolved).toEqual({});
  });

  it("keeps the document's rate text when the imported rate is applied unchanged", async () => {
    const incoming = profile(140);
    incoming.basics.rate_raw = "120–140 zł/h";
    const onApply = vi.fn();
    render(<ChampionImportReview initial={{ champion_profile: incoming }} sourceIsDocument onApply={onApply} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    // The server reads the budget (upper bound) and the range warning from it.
    expect(post.mock.calls[0][1].profile.basics.rate_value).toBe("140");
    expect(post.mock.calls[0][1].profile.basics.rate_raw).toBe("120–140 zł/h");
  });

  it("drops the source text once the rate is edited", async () => {
    const incoming = profile(140);
    incoming.basics.rate_raw = "120–140 zł/h";
    const onApply = vi.fn();
    render(<ChampionImportReview initial={{ champion_profile: incoming }} sourceIsDocument onApply={onApply} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Maksymalna stawka PLN/h"), { target: { value: "150" } });
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(post.mock.calls[0][1].profile.basics.rate_value).toBe("150");
    expect(post.mock.calls[0][1].profile.basics.rate_raw).toBeNull();
  });

  it("sends a kept current rate without its text — the server keeps the stored one", async () => {
    const current = profile(100);
    current.basics.rate_raw = "do 100 zł netto/h";
    const incoming = profile(150);
    incoming.basics.rate_raw = "150 zł/h";
    const onApply = vi.fn();
    render(<ChampionImportReview initial={{ champion_profile: incoming }} current={current} jobId={7} fingerprint={"a".repeat(64)} sourceIsDocument onApply={onApply} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(post.mock.calls[0][1].profile.basics.rate_value).toBe("100");
    // Neither the document's text (for another number) nor the stored one:
    // re-sending the stored text made the server re-read an unchanged budget.
    expect(post.mock.calls[0][1].profile.basics.rate_raw).toBeNull();
  });

  it("the reconcile dialog over the stored draft never re-sends the stored rate text", async () => {
    const draft = profile(140);
    draft.basics.rate_raw = "140 zł netto/h";
    const onApply = vi.fn();
    // `ChampionProfileEditor` → „Uzgodnij profil i pola rekrutacji”: no `current`,
    // no document — the dialog is built from the stored draft itself.
    render(<ChampionImportReview initial={{ champion_profile: draft }} jobId={7} fingerprint={"a".repeat(64)} onApply={onApply} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    for (const [, body] of post.mock.calls) {
      expect(body.profile.basics.rate_value).toBe("140");
      expect(body.profile.basics.rate_raw).toBeNull();
    }
    expect(post.mock.calls[1][0]).toBe("/api/jobs/7/champion-profile/apply-import");
  });

  it("the Word/PDF import button marks its preview as a document", async () => {
    const incoming = profile(140);
    incoming.basics.rate_raw = "do 140 zł netto/h";
    post.mockImplementation(async (url, body) => ({ data: url.endsWith("preview") ? { champion_profile: incoming } : { champion_profile: body.profile } }));
    const onApply = vi.fn();
    const { container } = render(<ChampionImportButton onApply={onApply} />);
    const input = container.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "profil.docx")] } });
    fireEvent.click(await screen.findByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    const validate = post.mock.calls.find(([url]) => url.endsWith("validate"))!;
    expect(validate[1].profile.basics.rate_raw).toBe("do 140 zł netto/h");
  });

  it("keeps accepted skills alongside fragments that still need review", async () => {
    const incoming = profile(150);
    incoming.stack.must = [{ name: "Python" }];
    incoming.intake!.unresolved["stack.must"] = "do ustalenia";
    const onApply = vi.fn();
    render(<ChampionImportReview initial={{ champion_profile: incoming }} onApply={onApply} onClose={() => {}} />);
    expect(screen.getByLabelText(/MUST — jeden wpis/)).toHaveValue("Python\ndo ustalenia");
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(post.mock.calls[0][1].profile.stack.must).toBe("Python\ndo ustalenia");
  });

  it("refreshes the comparison after 409 and requires applying the new snapshot", async () => {
    const onApply = vi.fn(); let conflicted = false;
    post.mockImplementation(async (url, body) => {
      if (url.endsWith("apply-import") && !conflicted) {
        conflicted = true;
        throw { response: { status: 409, data: { detail: { message: "Rekrutacja zmieniła się", champion_profile: profile(200), fingerprint: "b".repeat(64), job_values: {rate_value: 210} } } } };
      }
      return { data: { champion_profile: body.profile } };
    });
    render(<ChampionImportReview initial={{ champion_profile: profile(150) }} current={profile(100)} jobId={7} fingerprint={"a".repeat(64)} onApply={onApply} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await screen.findByText("Obecnie: 200");
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByText(/obecnie: 210/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Zastosuj / zapisz szkic"));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(post.mock.calls.at(-1)![1].expected_fingerprint).toBe("b".repeat(64));
    expect(post.mock.calls.at(-1)![1].profile.basics.rate_value).toBe("200");
  });

  it("uzgadnianie bez dokumentu ma własny tytuł, polskie wartości pól rekrutacji i bez pustej ramki dokumentu", () => {
    // UAT M04-B06: tytuł „Podgląd importu Championa” przy uzgadnianiu,
    // „(obecnie: remote)” i pusta ramka „Informacje z dokumentu”.
    const stored = profile(150);
    stored.intake = { ...stored.intake!, document_context: { client_name: "" } };
    render(<ChampionImportReview initial={{ champion_profile: stored }} jobId={7} jobValues={{ work_mode: "remote", must: ["Python", "SQL"] }} onApply={() => {}} onClose={() => {}} />);
    expect(screen.getByRole("heading", { name: "Uzgodnij profil i pola rekrutacji" })).toBeInTheDocument();
    expect(screen.queryByText("Podgląd importu Championa")).toBeNull();
    expect(screen.queryByText(/Informacje z dokumentu/)).toBeNull();
    expect(screen.getByText(/obecnie: zdalnie/)).toBeInTheDocument();
    expect(screen.queryByText(/obecnie: remote/)).toBeNull();
    expect(screen.getByText(/obecnie: Python, SQL/)).toBeInTheDocument();
    expect(screen.getByLabelText("Lokalizacja biura")).toBeInTheDocument();
  });

  it("import dokumentu zostaje „Podglądem importu Championa”", () => {
    render(<ChampionImportReview initial={{ champion_profile: profile(150) }} sourceIsDocument onApply={() => {}} onClose={() => {}} />);
    expect(screen.getByRole("heading", { name: "Podgląd importu Championa" })).toBeInTheDocument();
  });
});

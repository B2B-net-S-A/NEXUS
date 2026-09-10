import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChampionImportReview } from "../ChampionIntake";
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
});

/**
 * Wiersz rekrutacji, w której osoba już jest (16.10.2026): numer u klienta
 * i tytuł dla rekrutera jak w nagłówku; nazwa od klienta tylko w dymku.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobNameLabel } from "@/components/v2/jobs/JobNameLabel";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
const clipboard = vi.hoisted(() => ({ copyTextToClipboard: vi.fn(async () => true) }));

vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/clipboard", () => clipboard);

const JOB = {
  id: 7,
  title: "AI Engineer (ZOB-9001)",
  working_title: "Senior AI Engineer · Java, LLM · 5+ lat",
  client_reference: "ZOB-9001",
};

beforeEach(() => {
  toast.showSuccess.mockClear();
  clipboard.copyTextToClipboard.mockClear();
});

describe("JobNameLabel", () => {
  it("shows the client number and the recruiter title, not the client title", () => {
    render(<JobNameLabel job={JOB} />);
    expect(screen.getByText("ZOB-9001")).toBeInTheDocument();
    expect(screen.getByText("Senior AI Engineer · Java, LLM · 5+ lat")).toBeInTheDocument();
    expect(screen.queryByText("AI Engineer (ZOB-9001)")).not.toBeInTheDocument();
    // Nazwa od klienta zostaje w dymku tytułu.
    expect(
      screen.getByTitle(/^Senior AI Engineer · Java, LLM · 5\+ lat\s+Nazwa u klienta: AI Engineer \(ZOB-9001\)$/),
    ).toBeInTheDocument();
  });

  it("links the title to the recruitment and copies the number on its own", async () => {
    render(<JobNameLabel job={JOB} href="/jobs/7" />);
    const link = screen.getByRole("link", { name: "Senior AI Engineer · Java, LLM · 5+ lat" });
    expect(link).toHaveAttribute("href", "/jobs/7");
    await userEvent.click(screen.getByRole("button", { name: "Numer u klienta ZOB-9001 — kopiuj" }));
    expect(clipboard.copyTextToClipboard).toHaveBeenCalledWith("ZOB-9001");
    expect(toast.showSuccess).toHaveBeenCalledWith("Skopiowano numer u klienta");
  });

  it("inside another button the number is plain text, not a second button", () => {
    render(
      <button type="button">
        <JobNameLabel job={JOB} copyable={false} wrap />
      </button>,
    );
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button")).toHaveAccessibleName(/^ZOB-9001\s?Senior AI Engineer · Java, LLM · 5\+ lat$/);
  });

  it("without a recruiter title and number shows the client title alone", () => {
    render(<JobNameLabel job={{ id: 3, title: "Tester manualny" }} />);
    expect(screen.getByText("Tester manualny")).toBeInTheDocument();
    expect(screen.queryByTestId("job-name-client-reference")).not.toBeInTheDocument();
  });
});

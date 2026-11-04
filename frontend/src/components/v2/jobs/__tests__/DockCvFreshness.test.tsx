import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("@/lib/api", () => ({
  candidateStageCvApi: { original: { refresh: (...a: unknown[]) => refresh(...a) } },
}));
const toastSuccess = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: (...a: unknown[]) => toastSuccess(...a), showError: vi.fn() }),
}));

import { DockCvFreshness, profileReadPending } from "@/components/v2/jobs/DockCvFreshness";
import { dockOriginalCv, type DockOriginalCv, type DockProfileCvDoc } from "@/lib/dock-cv-summary";

const snapshot = (date: string, source: string | null = null, filename = "Anna_CV.pdf"): DockOriginalCv =>
  dockOriginalCv({
    snapshot: {
      has_snapshot: true,
      original_snapshot_at: date,
      original_cv_filename: filename,
      original_snapshot_source: source,
    },
    snapshotLoading: false,
    profileDocs: undefined,
    profileDocsFailed: false,
  });

const doc = (id: number, extra: Partial<DockProfileCvDoc> = {}): DockProfileCvDoc => ({
  id,
  filename: `cv-${id}.pdf`,
  is_primary: false,
  uploaded_at: null,
  created_at: "2026-10-01T10:00:00Z",
  ...extra,
});

function renderFreshness(props: Partial<Parameters<typeof DockCvFreshness>[0]> = {}) {
  const onShowProfileCv = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DockCvFreshness
        stageId={900}
        original={snapshot("2026-10-08T10:00:00Z")}
        profileDocs={[]}
        candidate={null}
        uploadedAt={null}
        onShowProfileCv={onShowProfileCv}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onShowProfileCv, client };
}

describe("profileReadPending", () => {
  const uploadedAt = Date.parse("2026-10-13T13:00:00Z");

  it("trwa do odczytu AI albo końca okna 3 minut", () => {
    expect(profileReadPending(uploadedAt, { cv_parsed_at: "2026-10-12T08:00:00Z" }, uploadedAt + 30_000)).toBe(true);
    expect(profileReadPending(uploadedAt, { cv_parsed_at: "2026-10-13T13:00:40Z" }, uploadedAt + 50_000)).toBe(false);
    expect(profileReadPending(uploadedAt, null, uploadedAt + 4 * 60_000)).toBe(false);
    expect(profileReadPending(null, null)).toBe(false);
  });
});

describe("DockCvFreshness", () => {
  beforeEach(() => {
    refresh.mockReset();
    toastSuccess.mockReset();
  });

  it("nic nie pokazuje, gdy kopia jest aktualna", () => {
    renderFreshness({ profileDocs: [doc(1, { is_primary: true, uploaded_at: "2026-10-01T10:00:00Z" })] });
    expect(screen.queryByTestId("dock-cv-freshness")).toBeNull();
  });

  it("„W profilu jest nowsze CV” → „Użyj w tej rekrutacji” podmienia kopię etapu", async () => {
    refresh.mockResolvedValue({ data: { has_snapshot: true, original_snapshot_source: "manual_refresh" } });
    const newer = doc(7, { is_primary: true, filename: "Anna_CV_2026.pdf", uploaded_at: "2026-10-13T09:00:00Z" });
    const { onShowProfileCv, client } = renderFreshness({ profileDocs: [doc(1), newer] });
    const user = userEvent.setup();

    expect(screen.getByText("W profilu jest nowsze CV")).toBeInTheDocument();
    expect(screen.getByText(/Anna_CV_2026\.pdf · 13\.10\.2026/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Pokaż" }));
    expect(onShowProfileCv).toHaveBeenCalledWith(7);

    await user.click(screen.getByRole("button", { name: /Użyj w tej rekrutacji/ }));
    await waitFor(() => expect(refresh).toHaveBeenCalledWith(900));
    expect(client.getQueryData(["cv-original", 900])).toMatchObject({ original_snapshot_source: "manual_refresh" });
    expect(toastSuccess).toHaveBeenCalledWith("CV z profilu jest teraz CV tej rekrutacji.");
  });

  it("po wgraniu: „AI czyta nowe CV”, dopóki profil nie ma odczytu", () => {
    renderFreshness({
      original: snapshot(new Date().toISOString(), "manual_upload"),
      uploadedAt: Date.now(),
      candidate: { cv_parsed_at: "2026-10-01T10:00:00Z" },
    });
    expect(screen.getByText(/Profil: AI czyta nowe CV/)).toBeInTheDocument();
  });
});

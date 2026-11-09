import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvGenerateConfirm } from "@/components/v2/recruitment/CvGenerateConfirm";
import api from "@/lib/api";
import { NO_CONFIRMATIONS } from "@/lib/cv-generate-confirm";

vi.mock("@/lib/api", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/api/screeningForm", () => ({ useScreeningFormState: () => ({ data: {} }) }));
vi.mock("@/lib/screening-summary", () => ({ screeningFormHref: () => "/x", screeningSummaryRows: () => [] }));
vi.mock("next/link", () => ({ default: ({ children }: { children: React.ReactNode }) => <span>{children}</span> }));

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);
const URL = "/api/pipeline/stages/7/qc/role-facts";

function setup(stageId: number | null = 7) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CvGenerateConfirm
        candidateId={1}
        jobId={2}
        files={[]}
        answers={null}
        existingNotes={0}
        fileId={null}
        onFileChange={() => undefined}
        noteDraft=""
        onNoteDraftChange={() => undefined}
        confirmed={NO_CONFIRMATIONS}
        onConfirm={() => undefined}
        left={["file", "answers", "notes"]}
        stageId={stageId}
      />
    </QueryClientProvider>,
  );
}

describe("Z rozmowy do opisu roli", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it("pokazuje cytat i zapisuje wskazaną rolę, a fakt znika z listy", async () => {
    get.mockResolvedValue({
      data: { facts: [{ term: "Kafka", quote: "Tak, od 2023 w projekcie płatności." }], roles: ["Firma A", "Firma B"] },
    });
    post.mockResolvedValue({ data: { facts: [], roles: ["Firma A", "Firma B"] } });
    setup();
    expect(await screen.findByText("„Tak, od 2023 w projekcie płatności.”")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("W której roli?"), "Firma B");
    await waitFor(() => expect(post).toHaveBeenCalledWith(URL, { term: "Kafka", role: "Firma B" }));
    await waitFor(() => expect(screen.queryByTestId("cv-role-facts")).toBeNull());
  });

  it("awaria zapisu pokazuje komunikat serwera", async () => {
    get.mockResolvedValue({ data: { facts: [{ term: "Kafka", quote: "Tak." }], roles: ["Firma A"] } });
    post.mockRejectedValue({ response: { status: 422, data: { detail: { message: "Odśwież okno." } } } });
    setup();
    await userEvent.selectOptions(await screen.findByLabelText("W której roli?"), "Firma A");
    expect(await screen.findByRole("alert")).toHaveTextContent("Odśwież okno.");
  });

  it("bez faktów, bez ról, przy błędzie i bez etapu kroku nie ma", async () => {
    get.mockResolvedValueOnce({ data: { facts: [], roles: ["Firma A"] } });
    const { unmount } = setup();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("cv-role-facts")).toBeNull();
    unmount();

    get.mockResolvedValueOnce({ data: { facts: [{ term: "Kafka", quote: "Tak." }], roles: [] } });
    const second = setup();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("cv-role-facts")).toBeNull();
    second.unmount();

    get.mockRejectedValueOnce(new Error("awaria"));
    const third = setup();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(3));
    expect(screen.queryByTestId("cv-role-facts")).toBeNull();
    third.unmount();

    setup(null);
    expect(get).toHaveBeenCalledTimes(3);
  });
});

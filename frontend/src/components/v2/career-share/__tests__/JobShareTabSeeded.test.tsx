import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));

import { JobShareTab } from "../JobShareTab";
import { ToastProvider } from "@/components/Toast";
import {
  inviteLinksQueryKey,
  jobPublicProfileQueryKey,
  shareablePublishedJobsQueryKey,
} from "@/lib/api/careerLinks";

describe("JobShareTab z danymi w cache przed pierwszym renderem", () => {
  it("pokazuje zapisany opis publiczny (nie wisi na „Wczytuję”)", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    qc.setQueryData(shareablePublishedJobsQueryKey(), [{ id: 101, title: "Senior Java Developer", status: "published" }]);
    qc.setQueryData(inviteLinksQueryKey(), []);
    qc.setQueryData(jobPublicProfileQueryKey(101), {
      job_id: 101, status: "draft", subtitle: "podtytuł", about: "O projekcie tekst",
      sections: { must: true, nice: true, params: true, process: true },
      show_on_recruiter_page: true, approved_at: null, approved_by_name: null, findings: [], preview: null,
    });
    render(
      <StrictMode>
        <QueryClientProvider client={qc}>
          <ToastProvider>
            <JobShareTab enabled defaultJobId={101} />
          </ToastProvider>
        </QueryClientProvider>
      </StrictMode>,
    );
    expect(screen.getByDisplayValue("O projekcie tekst")).toBeInTheDocument();
  });
});

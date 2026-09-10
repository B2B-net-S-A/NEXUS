import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { CvGeneratedShareModal } from "../CvGeneratedShareModal";

const api = vi.hoisted(() => ({ approve: vi.fn(), approvedVersions: vi.fn(), list: vi.fn(), create: vi.fn(), revoke: vi.fn() }));
vi.mock("@/lib/api", () => ({ cvGeneratedShareApi: api }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue({ data: [] });
  api.approvedVersions.mockImplementation(async (id: number) => ({ data: id === 7 ? [
    { id: 12, version: 2, language: "pl", approved_at: "2026-09-09T12:00:00Z", job_title: "Developer" },
    { id: 13, version: 3, language: "en", approved_at: "2026-09-09T13:00:00Z", job_title: "Engineer" },
  ] : [] }));
  api.create.mockResolvedValue({ data: { share_url_suffix: "/cv/i/test", interactive_available: false } });
});
it("requires an explicit approved version and clears it when the document changes", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const modal = (id: number) => <QueryClientProvider client={client}><CvGeneratedShareModal generatedId={id} onClose={() => {}} /></QueryClientProvider>;
  const view = render(modal(7));
  const user = userEvent.setup();
  await screen.findByRole("option", { name: /Wersja 2/ });
  expect(screen.getByRole("button", { name: "Wygeneruj link" })).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Zatwierdzona wersja CV"), "12");
  await user.click(screen.getByRole("button", { name: "Wygeneruj link" }));
  await waitFor(() => expect(api.create).toHaveBeenCalledWith(7, 14, undefined, 12));
  view.rerender(modal(8));
  await screen.findByText(/Brak zatwierdzonych wersji/);
  expect(screen.getByRole("button", { name: "Wygeneruj link" })).toBeDisabled();
  expect(screen.getByLabelText("Zatwierdzona wersja CV")).toHaveValue("");
  expect(api.create).toHaveBeenCalledTimes(1);
});

it("can approve an upload without a recruitment stage and share that approval", async () => {
  api.approvedVersions.mockResolvedValue({ data: [] });
  api.approve.mockImplementation(async () => {
    api.approvedVersions.mockResolvedValue({ data: [{ id: 21, version: 1, language: "pl", approved_at: "2026-09-09T12:00:00Z", job_title: "Engineer" }] });
    return { data: { document_version_id: 21, version: 1 } };
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CvGeneratedShareModal generatedId={8} onClose={() => {}} /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Zatwierdź wygenerowane CV" }));
  await waitFor(() => expect(screen.getByLabelText("Zatwierdzona wersja CV")).toHaveValue("21"));
  await user.click(screen.getByRole("button", { name: "Wygeneruj link" }));
  await waitFor(() => expect(api.create).toHaveBeenCalledWith(8, 14, undefined, 21));
  expect(api.approve).toHaveBeenCalledWith(8);
});

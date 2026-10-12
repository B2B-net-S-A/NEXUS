import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ originalGet: vi.fn(), pane: vi.fn() }));

vi.mock("@/lib/api", () => ({
  candidateStageCvApi: { original: { get: (...args: unknown[]) => mocks.originalGet(...args) } },
}));
// Treść panelu ciągnie pdf.js — tu wystarczy wiedzieć, z jaką parą się montuje.
vi.mock("next/dynamic", () => ({
  default: () =>
    function PaneStub(props: Record<string, unknown>) {
      mocks.pane(props);
      return <div data-testid="sources-pane" />;
    },
}));

import { CvEditorSources } from "../CvEditorSources";

function mount(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

it("ustala kandydata i rekrutację z kopii CV etapu", async () => {
  mocks.originalGet.mockResolvedValueOnce({ data: { candidate_id: 101, job_id: 201 } });
  mount(<CvEditorSources stageId={901} />);
  expect(screen.getByText("Wczytywanie źródeł…")).toBeInTheDocument();
  expect(await screen.findByTestId("sources-pane")).toBeInTheDocument();
  expect(mocks.originalGet).toHaveBeenCalledWith(901);
  expect(mocks.pane).toHaveBeenLastCalledWith(
    expect.objectContaining({ candidateId: 101, jobId: 201, stageId: 901 }),
  );
});

it("awaria odczytu nie wygląda jak brak źródeł i daje ponowić", async () => {
  mocks.originalGet.mockRejectedValueOnce(new Error("offline"));
  mocks.originalGet.mockResolvedValueOnce({ data: { candidate_id: 5, job_id: 6 } });
  mount(<CvEditorSources stageId={12} />);
  expect(await screen.findByText("Nie udało się wczytać źródeł tego CV.")).toBeInTheDocument();
  expect(screen.queryByText(/bez rekrutacji/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  expect(await screen.findByTestId("sources-pane")).toBeInTheDocument();
});

it("para podana wprost nie pyta o etap", () => {
  mocks.originalGet.mockClear();
  mount(<CvEditorSources context={{ candidateId: 7, jobId: 8, stageId: null }} />);
  expect(screen.getByTestId("sources-pane")).toBeInTheDocument();
  expect(mocks.originalGet).not.toHaveBeenCalled();
});

it("CV bez rekrutacji mówi, czemu panel jest pusty, i nie krzyczy błędem", () => {
  mount(<CvEditorSources context={null} />);
  expect(screen.getByText(/To CV powstało bez rekrutacji w NEXUSIE/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

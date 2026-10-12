import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  renderDocx: vi.fn(),
  align: vi.fn(),
  fit: vi.fn((..._args: unknown[]) => () => undefined),
}));

vi.mock("@/lib/docx-preview-safe", () => ({
  renderDocxSafely: (...args: unknown[]) => mocks.renderDocx(...args),
}));
vi.mock("@/lib/cv-docx-preview", () => ({
  alignB2bLetterheadPreview: (...args: unknown[]) => mocks.align(...args),
}));
vi.mock("@/lib/docx-fit", () => ({ observeDocxFit: (...args: unknown[]) => mocks.fit(...args) }));

import { CvEditorWordPreview } from "../CvEditorWordPreview";

afterEach(() => vi.clearAllMocks());

it("rysuje plik Word z bieżącej treści i dopasowuje stronę do szerokości", async () => {
  const blob = new Blob(["docx"]);
  const load = vi.fn().mockResolvedValue(blob);
  mocks.renderDocx.mockResolvedValue(undefined);
  render(<CvEditorWordPreview load={load} />);
  expect(screen.getByRole("status")).toHaveTextContent("Przygotowuję plik Word…");
  await waitFor(() => expect(mocks.renderDocx).toHaveBeenCalledWith(blob, expect.any(HTMLElement), expect.anything()));
  await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  expect(screen.getByLabelText("Podgląd pliku Word")).toBeVisible();
  expect(mocks.align).toHaveBeenCalledOnce();
  expect(mocks.fit).toHaveBeenCalledOnce();
});

it("odmowę serwera (brak zgody RODO) pokazuje jego słowami i daje ponowić", async () => {
  const load = vi
    .fn()
    .mockRejectedValueOnce({
      response: { status: 409, data: { detail: { code: "consent_required", message: "Dołącz zrzut zgody RODO." } } },
    })
    .mockResolvedValueOnce(new Blob(["docx"]));
  mocks.renderDocx.mockResolvedValue(undefined);
  render(<CvEditorWordPreview load={load} />);
  expect(await screen.findByText("Dołącz zrzut zgody RODO.")).toBeInTheDocument();
  expect(mocks.renderDocx).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
  await waitFor(() => expect(mocks.renderDocx).toHaveBeenCalledOnce());
  expect(load).toHaveBeenCalledTimes(2);
});

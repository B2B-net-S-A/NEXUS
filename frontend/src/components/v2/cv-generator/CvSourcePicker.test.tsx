import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CvSourcePicker, useCvSourceSelection } from "./CvSourcePicker";

vi.mock("@/lib/api", () => ({ default: { get: vi.fn(async (url: string) => ({data: [
  {id: url.includes("/2/") ? 72 : 71, filename: "source.docx", is_primary: true, uploaded_at: null},
]})) } }));

function Harness({ candidateId }: { candidateId: number }) {
  const selection = useCvSourceSelection(candidateId, true);
  return <><CvSourcePicker selection={selection} /><button disabled={!selection.selected}>Generate</button></>;
}

describe("CV source ownership", () => {
  it("does not carry a chosen source into a different candidate", async () => {
    const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
    const view = render(<QueryClientProvider client={client}><Harness candidateId={1} /></QueryClientProvider>);
    await screen.findByRole("option", {name: "source.docx · główne"});
    expect(screen.getByRole("button", {name: "Generate"})).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Plik do generacji"), {target: {value: "71"}});
    expect(screen.getByRole("button", {name: "Generate"})).toBeEnabled();
    view.rerender(<QueryClientProvider client={client}><Harness candidateId={2} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("button", {name: "Generate"})).toBeDisabled());
    await screen.findByRole("option", {name: "source.docx · główne"});
    expect(screen.getByLabelText("Plik do generacji")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Plik do generacji"), {target: {value: "72"}});
    expect(screen.getByRole("button", {name: "Generate"})).toBeEnabled();
  });
});

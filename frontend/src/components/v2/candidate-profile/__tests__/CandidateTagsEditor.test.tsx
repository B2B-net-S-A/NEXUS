import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const addCandidateTag = vi.fn();
const removeCandidateTag = vi.fn();
const suggestCandidateTags = vi.fn();

vi.mock("@/lib/api/candidateTags", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/candidateTags")>();
  return {
    ...actual,
    addCandidateTag: (...args: unknown[]) => addCandidateTag(...args),
    removeCandidateTag: (...args: unknown[]) => removeCandidateTag(...args),
    suggestCandidateTags: (...args: unknown[]) => suggestCandidateTags(...args),
  };
});

const showError = vi.fn();
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess: vi.fn() }) }));

import { CandidateTagsEditor, tagChips } from "../CandidateTagsEditor";
import { hasStringTag, normalizeTagInput } from "@/lib/api/candidateTags";
import { decodeFilters, encodeFilters, filtersToApiParams, DEFAULT_FILTERS } from "@/lib/url-filters";

const SOURCE = { type: "traffit_source", value: "LinkedIn", domain: "linkedin.com" };

function renderEditor(tags: unknown, canEdit = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CandidateTagsEditor candidateId={7} tags={tags} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  addCandidateTag.mockReset();
  removeCandidateTag.mockReset();
  suggestCandidateTags.mockReset().mockResolvedValue([]);
  showError.mockReset();
});

describe("tagChips / normalizeTagInput", () => {
  it("import objects are shown but not removable, duplicates collapse", () => {
    expect(tagChips(["senior", SOURCE, "Senior"])).toEqual([
      { label: "senior", removable: true },
      { label: "LinkedIn", removable: false },
    ]);
  });

  it("mirrors the backend validator", () => {
    expect(normalizeTagInput("  Kafka   Streams ")).toEqual({ tag: "Kafka Streams", error: null });
    expect(normalizeTagInput("a,b").tag).toBeNull();
    expect(normalizeTagInput("x".repeat(65)).error).toMatch(/64/);
    expect(normalizeTagInput("   ")).toEqual({ tag: null, error: null });
    expect(hasStringTag(["Java", SOURCE], "java")).toBe(true);
    expect(hasStringTag([SOURCE], "LinkedIn")).toBe(false);
  });
});

describe("CandidateTagsEditor", () => {
  it("read-only without candidate.write — no add/remove controls", () => {
    renderEditor(["senior", SOURCE], false);
    expect(screen.getByText("#senior")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usuń tag/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Tag/ })).toBeNull();
  });

  it("adds ONE tag via the single-tag endpoint", async () => {
    addCandidateTag.mockResolvedValue({ tags: ["senior", SOURCE, "Kafka"], changed: true });
    renderEditor(["senior", SOURCE]);
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));
    fireEvent.change(screen.getByLabelText("Nowy tag"), { target: { value: " Kafka " } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
    await waitFor(() => expect(addCandidateTag).toHaveBeenCalledWith(7, "Kafka"));
  });

  it("blocks a duplicate before sending", () => {
    renderEditor(["senior"]);
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));
    fireEvent.change(screen.getByLabelText("Nowy tag"), { target: { value: "SENIOR" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Kandydat ma już ten tag.");
    expect(screen.getByRole("button", { name: "Dodaj" })).toBeDisabled();
  });

  it("removes only the clicked string tag", async () => {
    removeCandidateTag.mockResolvedValue({ tags: [SOURCE], changed: true });
    renderEditor(["senior", SOURCE]);
    expect(screen.queryByRole("button", { name: "Usuń tag LinkedIn" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Usuń tag senior" }));
    await waitFor(() => expect(removeCandidateTag).toHaveBeenCalledWith(7, "senior"));
  });

  it("server refusal is shown, not swallowed", async () => {
    addCandidateTag.mockRejectedValue({ response: { status: 422, data: { detail: "Kandydat może mieć najwyżej 50 tagów." } } });
    renderEditor([]);
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));
    fireEvent.change(screen.getByLabelText("Nowy tag"), { target: { value: "nowy" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith("Kandydat może mieć najwyżej 50 tagów."));
  });
});

describe("tags list filter", () => {
  it("round-trips through the URL and reaches the API as repeated `tags`", () => {
    const filters = { ...DEFAULT_FILTERS, tags: ["senior", "bankowość"] };
    const decoded = decodeFilters(encodeFilters(filters));
    expect(decoded.tags).toEqual(["senior", "bankowość"]);
    expect(filtersToApiParams(decoded, 1).tags).toEqual(["senior", "bankowość"]);
    expect(filtersToApiParams(DEFAULT_FILTERS, 1).tags).toBeUndefined();
  });
});

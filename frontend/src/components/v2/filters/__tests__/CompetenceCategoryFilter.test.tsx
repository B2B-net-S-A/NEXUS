import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CompetenceCategoryFilter } from "@/components/v2/filters/CompetenceCategoryFilter";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    competenceCategoriesApi: {
      list: vi.fn(),
    },
  };
});

import { competenceCategoriesApi } from "@/lib/api";

const FAKE_CCS = [
  {
    id: 1,
    slug: "infra",
    name_pl: "Infrastruktura",
    name_en: "Infrastructure",
    description: "",
    keywords: [],
    display_order: 1,
  },
  {
    id: 2,
    slug: "dev",
    name_pl: "Rozwój oprogramowania",
    name_en: "Development",
    description: "",
    keywords: [],
    display_order: 2,
  },
  {
    id: 3,
    slug: "data-ai",
    name_pl: "Dane i AI",
    name_en: "Data & AI",
    description: "",
    keywords: [],
    display_order: 3,
  },
];

describe("CompetenceCategoryFilter", () => {
  beforeEach(() => {
    vi.mocked(competenceCategoriesApi.list).mockResolvedValue(FAKE_CCS);
  });

  it("renders skeleton until categories load", async () => {
    let resolve!: (rows: typeof FAKE_CCS) => void;
    vi.mocked(competenceCategoriesApi.list).mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    render(<CompetenceCategoryFilter selected={[]} onChange={vi.fn()} />);
    expect(screen.getByRole("group")).toBeInTheDocument();
    // 5 skeleton tiles regardless of fetched count
    expect(screen.getByRole("group").querySelectorAll(".animate-pulse")).toHaveLength(
      5,
    );
    resolve(FAKE_CCS);
    await waitFor(() =>
      expect(screen.getByText("Rozwój oprogramowania")).toBeInTheDocument(),
    );
  });

  it("renders one chip per category after fetch", async () => {
    render(<CompetenceCategoryFilter selected={[]} onChange={vi.fn()} />);
    for (const cc of FAKE_CCS) {
      expect(await screen.findByText(cc.name_pl)).toBeInTheDocument();
    }
  });

  it("multi mode: clicking a chip adds it to selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <CompetenceCategoryFilter selected={[]} onChange={onChange} mode="multi" />,
    );
    await user.click(await screen.findByText("Dane i AI"));
    expect(onChange).toHaveBeenLastCalledWith([3]);
  });

  it("multi mode: clicking again removes it", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <CompetenceCategoryFilter
        selected={[2]}
        onChange={onChange}
        mode="multi"
      />,
    );
    await user.click(await screen.findByText("Rozwój oprogramowania"));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("single mode: clicking another chip replaces selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <CompetenceCategoryFilter
        selected={[1]}
        onChange={onChange}
        mode="single"
      />,
    );
    await user.click(await screen.findByText("Dane i AI"));
    expect(onChange).toHaveBeenLastCalledWith([3]);
  });

  it("renders facet count badge when counts provided", async () => {
    render(
      <CompetenceCategoryFilter
        selected={[]}
        onChange={vi.fn()}
        counts={{ 1: 7, 2: 23 }}
      />,
    );
    await screen.findByText("Infrastruktura");
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("23")).toBeInTheDocument();
  });

  it("aria-checked tracks selection in single mode", async () => {
    render(
      <CompetenceCategoryFilter
        selected={[2]}
        onChange={vi.fn()}
        mode="single"
      />,
    );
    const chip = await screen.findByRole("radio", {
      name: /Rozwój oprogramowania/i,
    });
    expect(chip).toHaveAttribute("aria-checked", "true");
  });

  it("aria-checked tracks selection in multi mode", async () => {
    render(
      <CompetenceCategoryFilter selected={[3]} onChange={vi.fn()} mode="multi" />,
    );
    const chip = await screen.findByRole("checkbox", { name: /Dane i AI/i });
    expect(chip).toHaveAttribute("aria-checked", "true");
  });

  it("shows error message when fetch fails", async () => {
    vi.mocked(competenceCategoriesApi.list).mockRejectedValueOnce(
      new Error("Network down"),
    );
    render(<CompetenceCategoryFilter selected={[]} onChange={vi.fn()} />);
    expect(await screen.findByText(/Network down/i)).toBeInTheDocument();
  });
});

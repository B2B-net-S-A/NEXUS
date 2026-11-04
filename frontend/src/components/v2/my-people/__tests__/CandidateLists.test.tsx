import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Listy kandydatów w „Moich ludziach” (25.10.2026): nowa lista „Tylko ja”,
// przełącznik „Widzi zespół” u właściciela, cudza lista tylko do podglądu,
// awaria wczytania nie wygląda jak „nie masz list”.

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const toast = { showSuccess: vi.fn(), showError: vi.fn() };
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: http, default: http }));

vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (s: { user: { id: number; name: string } }) => unknown) =>
    select({ user: { id: 7, name: "Anna Przykładowa" } }),
}));

import {
  addedLabel,
  ListsTab,
} from "../CandidateListsViews";
import { AddToListButton } from "@/components/v2/candidate-profile/AddToListButton";
import { memberSkills, splitCandidateLists, type TalentPoolOut } from "@/lib/api/candidateLists";

function pool(over: Partial<TalentPoolOut>): TalentPoolOut {
  return {
    id: 1,
    name: "Lista",
    description: null,
    candidate_count: 0,
    created_at: "2026-10-20T10:00:00Z",
    is_personal: true,
    owner_id: 7,
    owner_name: "Anna Przykładowa",
    is_marketplace: false,
    team_visible: false,
    ...over,
  };
}

const POOLS = [
  pool({ id: 1, name: "Seniorzy DevOps", candidate_count: 2 }),
  pool({ id: 2, name: "Od Jana", owner_id: 9, owner_name: "Jan Testowy", team_visible: true, candidate_count: 4 }),
  pool({ id: 3, name: "SRE/DevOps", is_personal: false, owner_id: null, team_visible: true }),
];

const MEMBERS = {
  pool: { id: 1, name: "Seniorzy DevOps", candidate_count: 1, is_personal: true, owner_id: 7, team_visible: false },
  total: 1,
  candidates: [
    {
      id: 501,
      name: "Piotr",
      lastname: "Próbny",
      location: "Gdańsk, PL",
      skills: ["Kubernetes", { name: "Terraform" }, "AWS", "Docker"],
      added_at: "2026-10-20T10:00:00Z",
    },
  ],
};

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  for (const fn of Object.values(http)) fn.mockReset();
  toast.showSuccess.mockReset();
  toast.showError.mockReset();
});

describe("splitCandidateLists", () => {
  it("keeps only personal lists and splits mine from team-shared", () => {
    const { mine, shared } = splitCandidateLists(
      [...POOLS, pool({ id: 4, owner_id: 9, team_visible: false }), pool({ id: 5, is_marketplace: true })],
      7,
    );
    expect(mine.map((l) => l.id)).toEqual([1]);
    // Cudza lista „Tylko ja” nie przyjdzie z serwera, ale gdyby — nie pokazujemy.
    expect(shared.map((l) => l.id)).toEqual([2]);
  });

  it("gives an anonymous viewer no own lists", () => {
    expect(splitCandidateLists(POOLS, null).mine).toEqual([]);
  });
});

describe("member helpers", () => {
  it("reads skills given as strings or objects, at most three", () => {
    expect(memberSkills(MEMBERS.candidates[0])).toEqual(["Kubernetes", "Terraform", "AWS"]);
    expect(memberSkills({ skills: null })).toEqual([]);
  });

  it("says how long ago the person was added", () => {
    const now = new Date("2026-10-25T12:00:00Z");
    expect(addedLabel("2026-10-25T08:00:00Z", now)).toBe("dodany dziś");
    expect(addedLabel("2026-10-24T08:00:00Z", now)).toBe("dodany wczoraj");
    expect(addedLabel("2026-10-20T08:00:00Z", now)).toBe("dodany 5 dni temu");
  });
});

describe("ListsTab", () => {
  it("shows a failure with retry instead of „no lists yet”", async () => {
    http.get.mockRejectedValueOnce({ response: { status: 500 } });
    wrap(<ListsTab userId={7} onAdd={vi.fn()} />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/Nie masz jeszcze żadnej listy/)).not.toBeInTheDocument();
  });

  it("lists mine with visibility and shared lists with their owner", async () => {
    http.get.mockResolvedValueOnce({ data: POOLS });
    wrap(<ListsTab userId={7} onAdd={vi.fn()} />);
    expect(await screen.findByText("Seniorzy DevOps")).toBeInTheDocument();
    expect(screen.getByText("Tylko ja")).toBeInTheDocument();
    expect(screen.getByText("Od Jana")).toBeInTheDocument();
    expect(screen.getByText(/Jan Testowy/)).toBeInTheDocument();
    // Pula firmowa nie jest listą.
    expect(screen.queryByText("SRE/DevOps")).not.toBeInTheDocument();
  });

  it("creates a new list as „only me”", async () => {
    const user = userEvent.setup();
    http.get.mockResolvedValue({ data: [] });
    http.post.mockResolvedValueOnce({ data: pool({ id: 11, name: "Java — styczeń" }) });
    wrap(<ListsTab userId={7} onAdd={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: /Nowa lista/ }));
    await user.type(screen.getByRole("textbox", { name: "Nazwa nowej listy" }), "  Java — styczeń ");
    await user.click(screen.getByRole("button", { name: "Utwórz" }));
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith("/api/talent-pools", {
        name: "Java — styczeń",
        is_personal: true,
        team_visible: false,
      }),
    );
  });

  it("lets the owner share the list and remove people", async () => {
    const user = userEvent.setup();
    http.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("/candidates") ? MEMBERS : POOLS }),
    );
    http.patch.mockResolvedValueOnce({ data: pool({ id: 1, team_visible: true }) });
    http.delete.mockResolvedValueOnce({ data: {} });
    const onAdd = vi.fn();
    wrap(<ListsTab userId={7} onAdd={onAdd} />);
    await user.click(await screen.findByRole("button", { name: /Seniorzy DevOps/ }));
    expect(await screen.findByText("Piotr Próbny")).toBeInTheDocument();
    expect(screen.getByText(/Kubernetes, Terraform, AWS · Gdańsk, PL/)).toBeInTheDocument();

    await user.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(http.patch).toHaveBeenCalledWith("/api/talent-pools/1", { team_visible: true }),
    );

    await user.click(screen.getByRole("button", { name: "Dodaj do rekrutacji: Piotr Próbny" }));
    expect(onAdd).toHaveBeenCalledWith({ candidate_id: 501, full_name: "Piotr Próbny" });

    await user.click(screen.getByRole("button", { name: "Usuń z listy: Piotr Próbny" }));
    await waitFor(() =>
      expect(http.delete).toHaveBeenCalledWith("/api/talent-pools/1/remove/501"),
    );
  });

  it("shows someone else's list read-only, still with „add to recruitment”", async () => {
    const user = userEvent.setup();
    http.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.endsWith("/candidates")
          ? { ...MEMBERS, pool: { ...MEMBERS.pool, id: 2, owner_id: 9, team_visible: true } }
          : POOLS,
      }),
    );
    wrap(<ListsTab userId={7} onAdd={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: /Od Jana/ }));
    expect(await screen.findByText("Piotr Próbny")).toBeInTheDocument();
    expect(screen.getByText(/tylko podgląd/)).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usuń z listy/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usuń listę/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dodaj do rekrutacji: Piotr Próbny" })).toBeInTheDocument();
  });
});

describe("AddToListButton", () => {
  function mockLists(memberOf: number[]) {
    http.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes("for-candidate") ? { pool_ids: memberOf } : POOLS,
      }),
    );
  }

  it("counts only my lists on the button", async () => {
    // 2 = cudza lista zespołu, 3 = pula firmowa — nie są „moimi listami”.
    mockLists([1, 2, 3]);
    wrap(<AddToListButton candidateId={501} />);
    expect(await screen.findByRole("button", { name: "Na listach: 1" })).toBeInTheDocument();
  });

  it("adds to an unticked list and removes from a ticked one", async () => {
    const user = userEvent.setup();
    mockLists([]);
    http.post.mockResolvedValue({ data: {} });
    wrap(<AddToListButton candidateId={501} />);
    await user.click(await screen.findByRole("button", { name: "Na listę" }));
    const item = await screen.findByRole("button", { name: /Seniorzy DevOps/ });
    expect(item).toHaveAttribute("aria-pressed", "false");
    await user.click(item);
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith("/api/talent-pools/1/add", { candidate_id: 501 }),
    );
  });

  it("creates a private list and puts the person on it", async () => {
    const user = userEvent.setup();
    mockLists([]);
    http.post
      .mockResolvedValueOnce({ data: pool({ id: 12, name: "Nowa" }) })
      .mockResolvedValueOnce({ data: {} });
    wrap(<AddToListButton candidateId={501} />);
    await user.click(await screen.findByRole("button", { name: "Na listę" }));
    await user.type(await screen.findByRole("textbox", { name: "Nazwa nowej listy" }), "Nowa");
    await user.click(screen.getByRole("button", { name: "Utwórz listę i dodaj osobę" }));
    await waitFor(() =>
      expect(http.post).toHaveBeenLastCalledWith("/api/talent-pools/12/add", { candidate_id: 501 }),
    );
    expect(http.post).toHaveBeenCalledWith("/api/talent-pools", {
      name: "Nowa",
      is_personal: true,
      team_visible: false,
    });
  });
});

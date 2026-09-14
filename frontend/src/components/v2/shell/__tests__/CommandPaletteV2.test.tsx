import { act, fireEvent, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));

vi.mock("@/lib/api", () => ({ default: { get: apiGet } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => new Proxy({}, { get: () => true }),
}));
vi.mock("@/lib/section-access", () => ({ hasSectionAccess: () => true }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: unknown }) => unknown) =>
    selector({ user: { id: 1, role: "admin" } }),
}));
// cmdk w jsdom wymaga ResizeObserver/scrollIntoView — test dotyczy wyłącznie
// zapytań palety, więc prymitywy renderujemy jako zwykłe elementy.
vi.mock("@/components/ui/command", () => {
  const Pass = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    CommandDialog: Pass,
    CommandEmpty: Pass,
    CommandGroup: Pass,
    CommandItem: Pass,
    CommandList: Pass,
    CommandSeparator: () => null,
    CommandShortcut: Pass,
    CommandInput: ({
      value,
      onValueChange,
      placeholder,
    }: {
      value: string;
      onValueChange: (v: string) => void;
      placeholder?: string;
    }) => (
      <input
        placeholder={placeholder}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
      />
    ),
  };
});

import { CommandPaletteV2 } from "@/components/v2/shell/CommandPaletteV2";

beforeEach(() => {
  vi.useFakeTimers();
  apiGet.mockResolvedValue({ data: { items: [], total: 0 } });
});

afterEach(() => {
  vi.useRealTimers();
  apiGet.mockReset();
});

describe("CommandPaletteV2 — wyszukiwanie kandydatów", () => {
  it("pyta o kandydatów z sortowaniem po trafności (UAT M00-B01)", async () => {
    const { getByPlaceholderText } = render(
      <CommandPaletteV2 open onOpenChange={() => {}} />,
    );

    fireEvent.change(getByPlaceholderText(/Szukaj kandydatów/), {
      target: { value: "jan.kowalski@example.com" },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    const candidateCall = apiGet.mock.calls.find(
      ([url]) => url === "/api/candidates",
    );
    expect(candidateCall).toBeDefined();
    expect(candidateCall?.[1]?.params).toMatchObject({
      q: "jan.kowalski@example.com",
      page_size: 5,
      sort: "relevance",
    });
  });
});

describe("CommandPaletteV2 — nawigacja po wpisaniu zapytania (UAT M00-B03)", () => {
  it.each([
    ["kand", "Kandydaci"],
    ["rekr", "Rekrutacje"],
    ["klien", "Klienci"],
    ["ustaw", "Ustawienia"],
  ])("'%s' podpowiada pozycję %s", async (term, label) => {
    const { getByPlaceholderText, getByText } = render(
      <CommandPaletteV2 open onOpenChange={() => {}} />,
    );
    fireEvent.change(getByPlaceholderText(/Szukaj kandydatów/), {
      target: { value: term },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(getByText(label)).toBeTruthy();
  });

  it("dopasowanie ignoruje polskie znaki i wielkość liter", async () => {
    const { navMatches } = await import(
      "@/components/v2/shell/CommandPaletteV2"
    );
    expect(navMatches("Kalendarz", "KALE")).toBe(true);
    expect(navMatches("Ustawienia", "ustąw")).toBe(true);
    expect(navMatches("Klienci", "kontr")).toBe(false);
  });
});

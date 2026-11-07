import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { ScreenGuide } from "@/lib/jarvis/types";
import { JarvisPanel, type JarvisPanelProps } from "../JarvisPanel";

// Pusty panel pokazuje pytania, które ludzie zadawali na ekranie (decyzja
// 07.11.2026) — zamiast dymka ekranu: 714 pokazań, 2 otwarcia przewodnika.

const REPO = resolve(__dirname, "../../../../..");
const guides: ScreenGuide[] = JSON.parse(
  readFileSync(resolve(REPO, "backend/app/data/screen_guides/guides.json"), "utf8"),
);
const guide = (key: string) => guides.find((g) => g.key === key);

function panelProps(overrides: Partial<JarvisPanelProps> = {}): JarvisPanelProps {
  const noop = vi.fn();
  return {
    name: "Jarvis",
    character: "robot",
    accent: "primary",
    mood: "idle",
    view: "chat",
    items: [],
    thinking: false,
    streaming: false,
    draft: "",
    suggestions: [],
    onDraftChange: noop,
    onSend: noop,
    onNewChat: noop,
    onShowHistory: noop,
    onBackToChat: noop,
    onSelectConversation: noop,
    onDeleteConversation: noop,
    onOpenAppearance: noop,
    onClose: noop,
    onConfirm: noop,
    onReject: noop,
    inline: true,
    ...overrides,
  };
}

describe("„Na tym ekranie ludzie pytali”", () => {
  it("Tablica: cztery pytania z przewodnika, klik wysyła pytanie", () => {
    const asked = guide("jobs.board")?.asked ?? [];
    expect(asked).toEqual([
      "Jak zmienić liczbę wakatów?",
      "Dlaczego przy części kart nie ma wyniku dopasowania?",
      "Kto może przenieść kandydata na „Zatrudniony”?",
      "Gdzie jest briefing dla rekrutera?",
    ]);
    const onSend = vi.fn();
    render(<JarvisPanel {...panelProps({ screenQuestions: asked, onSend })} />);
    const section = screen.getByTestId("jarvis-screen-questions");
    expect(within(section).getByText("Na tym ekranie ludzie pytali")).toBeInTheDocument();
    expect(within(section).getAllByRole("button")).toHaveLength(4);
    // Podtytuł „Tyle mogę zrobić…:” nie wskazuje na pytania.
    expect(screen.getByText("Kliknij pytanie albo napisz własne.")).toBeInTheDocument();
    fireEvent.click(within(section).getByRole("button", { name: "Jak zmienić liczbę wakatów?" }));
    expect(onSend).toHaveBeenCalledWith("Jak zmienić liczbę wakatów?");
  });

  it("ekran bez listy pokazuje dzisiejszy pusty stan bez sekcji", () => {
    expect(guide("calendar")?.asked ?? []).toEqual([]);
    render(<JarvisPanel {...panelProps({ screenQuestions: guide("calendar")?.asked })} />);
    expect(screen.queryByTestId("jarvis-screen-questions")).toBeNull();
    expect(screen.getByText("Cześć, tu Jarvis!")).toBeInTheDocument();
    expect(screen.getByText(/Zapytaj o kandydatów, rekrutacje czy klientów/)).toBeInTheDocument();
  });

  it("niedostępny asystent nie podsuwa pytań, których nie wyśle", () => {
    render(
      <JarvisPanel
        {...panelProps({ screenQuestions: ["Jak zmienić liczbę wakatów?"], unavailableNote: "Asystent jest wyłączony." })}
      />,
    );
    expect(screen.queryByTestId("jarvis-screen-questions")).toBeNull();
  });

  it("w trakcie odpowiedzi pytania są wyłączone", () => {
    render(<JarvisPanel {...panelProps({ screenQuestions: ["Gdzie zmienić liczbę osób?"], streaming: true })} />);
    expect(screen.getByRole("button", { name: "Gdzie zmienić liczbę osób?" })).toBeDisabled();
  });

  it("pytanie z sekcji nie powtarza się w podpowiedziach pod polem", () => {
    const q = "Jak zgłosić urlop albo przerwę?";
    render(<JarvisPanel {...panelProps({ screenQuestions: [q], suggestions: [q, "Co NEXUS ustawi w Outlooku?"] })} />);
    expect(screen.getAllByRole("button", { name: q })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Co NEXUS ustawi w Outlooku?" })).toBeInTheDocument();
  });

  it("ekrany z decyzji 07.11 mają listę, każda najwyżej 4 pytania", () => {
    const expected: Record<string, number> = {
      "jobs.board": 4,
      "jobs.list": 3,
      "candidate.profile": 3,
      "hr.my_time": 3,
      "hr.approvals": 1,
      "client.orders": 2,
      "job.champion": 2,
    };
    for (const [key, count] of Object.entries(expected)) expect(guide(key)?.asked).toHaveLength(count);
    for (const g of guides) expect((g.asked ?? []).length).toBeLessThanOrEqual(4);
  });
});

describe("dymek ekranu wyłączony (07.11.2026)", () => {
  it("JarvisRoot nie pokazuje dymka „Kliknij, pokażę, jak tu działać”", () => {
    const root = readFileSync(resolve(__dirname, "../JarvisRoot.tsx"), "utf8");
    expect(root).not.toMatch(/screen_tip"|setScreenTip|Kliknij, pokażę, jak tu działać/);
    expect(root).toMatch(/screenQuestions=\{currentGuide\?\.asked\}/);
    // Dymek „utknięcia” zostaje.
    expect(root).toMatch(/stuck_shown/);
  });
});

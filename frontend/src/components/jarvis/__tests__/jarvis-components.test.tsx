import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JarvisActionCard } from "../JarvisActionCard";
import { JarvisMarkdown, isInternalHref } from "../JarvisMarkdown";
import { JarvisPanel, type JarvisPanelProps } from "../JarvisPanel";
import { JarvisGuideCard } from "../JarvisGuideCard";
import { HelpSpotlight, showHelpAnchor } from "../HelpSpotlight";
import { act } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("Markdown Jarvisa", () => {
  it("nie renderuje obrazków — adres obrazka to kanał wycieku", () => {
    const { container } = render(<JarvisMarkdown>{"![tajne](https://zly.example/x?d=123)"}</JarvisMarkdown>);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("tajne")).toBeInTheDocument();
  });

  it("linkuje tylko ścieżki wewnętrzne", () => {
    const { container } = render(
      <JarvisMarkdown>{"[Jan](/candidates/12) i [zły](https://zly.example) i [podwójny](//zly.example)"}</JarvisMarkdown>,
    );
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/candidates/12"]);
  });

  it("nie linkuje `/\\evil` — backslash przeglądarka czyta jak ukośnik (AI-01)", () => {
    expect(isInternalHref("/\\evil.example/x")).toBe(false);
    expect(isInternalHref("/\\/evil.example")).toBe(false);
    expect(isInternalHref("/jobs/5")).toBe(true);
    const { container } = render(
      <JarvisMarkdown>{"[zły](/\\evil.example/x) i [ok](/jobs/5)"}</JarvisMarkdown>,
    );
    for (const a of container.querySelectorAll("a")) {
      expect(a.getAttribute("href")).not.toMatch(/^\/\\/);
    }
  });
});

describe("karta akcji", () => {
  const action = { id: "a1", tool: "create_note", status: "proposed" as const, preview: { text: "Dodam **notatkę**" } };

  it("propozycja ma „Zrób to” i „Anuluj”", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    render(<JarvisActionCard action={action} onConfirm={onConfirm} onReject={onReject} />);
    fireEvent.click(screen.getByRole("button", { name: "Zrób to" }));
    fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(onConfirm).toHaveBeenCalledWith(action);
    expect(onReject).toHaveBeenCalledWith(action);
  });

  it("po wykonaniu nie ma już przycisków", () => {
    render(<JarvisActionCard action={{ ...action, status: "executed" }} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Wykonane")).toBeInTheDocument();
  });

  it("błąd pokazuje powód", () => {
    render(<JarvisActionCard action={{ ...action, status: "failed", result: { error: "Brak uprawnień" } }} />);
    expect(screen.getByText("Nie udało się: Brak uprawnień")).toBeInTheDocument();
  });
});

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
    suggestions: ["Co mam dziś do zrobienia?"],
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

describe("karta akcji — pełna treść (SEC-07)", () => {
  it("pokazuje całą treść notatki jako zwykły tekst", () => {
    const body = "Linia 1\n**nie pogrubiaj** " + "x".repeat(500) + " KONIEC";
    render(
      <JarvisActionCard
        action={{ id: "a2", tool: "create_note", status: "proposed", preview: { text: "Dodam notatkę", body } }}
      />,
    );
    const pre = screen.getByTestId("jarvis-action-body");
    expect(pre.tagName).toBe("PRE");
    expect(pre.textContent).toBe(body);
    expect(pre.querySelector("strong")).toBeNull();
  });
});

describe("panel", () => {
  it("Enter wysyła, Shift+Enter nie", () => {
    const onSend = vi.fn();
    render(<JarvisPanel {...panelProps({ draft: "  Cześć  ", onSend })} />);
    const input = screen.getByLabelText("Wiadomość do asystenta");
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Cześć");
  });

  it("podpowiedź wysyła się jednym kliknięciem", () => {
    const onSend = vi.fn();
    render(<JarvisPanel {...panelProps({ onSend })} />);
    fireEvent.click(screen.getByRole("button", { name: "Co mam dziś do zrobienia?" }));
    expect(onSend).toHaveBeenCalledWith("Co mam dziś do zrobienia?");
  });

  it("niedostępny asystent blokuje pole i mówi dlaczego", () => {
    render(<JarvisPanel {...panelProps({ draft: "hej", unavailableNote: "Asystent jest chwilowo wyłączony." })} />);
    expect(screen.getByText("Asystent jest chwilowo wyłączony.")).toBeInTheDocument();
    expect(screen.getByLabelText("Wiadomość do asystenta")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDisabled();
  });

  it("w trakcie odpowiedzi nie da się wysłać kolejnej wiadomości", () => {
    render(<JarvisPanel {...panelProps({ draft: "hej", streaming: true })} />);
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDisabled();
  });
});

describe("okno wyglądu (zgłoszenie 21.09: „Zapisz” ucięty na niskim ekranie)", () => {
  it("przyciski są w stałej stopce poza przewijaną treścią i wysyłają formularz", async () => {
    const { JarvisAppearanceDialog } = await import("../JarvisAppearanceDialog");
    const onSave = vi.fn();
    render(
      <JarvisAppearanceDialog
        open
        onOpenChange={vi.fn()}
        prefs={{
          character: "robot",
          name: "Jarvis",
          accent: "primary",
          enabled: true,
          minimized: false,
          sound: false,
          daily_brief: true,
          screen_tips: true,
          notes: [],
          unlocked_characters: ["robot", "owl"],
          locked_characters: {},
        }}
        onSave={onSave}
      />,
    );
    const input = screen.getByLabelText("Imię asystenta");
    const save = screen.getByRole("button", { name: "Zapisz" });
    // „Zapisz” NIE siedzi w przewijanej treści — inaczej może się uciąć.
    expect(input.closest(".overflow-y-auto")).not.toBeNull();
    expect(input.closest(".overflow-y-auto")?.contains(save)).toBe(false);

    fireEvent.change(input, { target: { value: "  Pan   Sowa " } });
    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ name: "Pan Sowa" }));
  });

  it("niepoprawne imię blokuje „Zapisz” w stopce", async () => {
    const { JarvisAppearanceDialog } = await import("../JarvisAppearanceDialog");
    render(
      <JarvisAppearanceDialog
        open
        onOpenChange={vi.fn()}
        prefs={{
          character: "robot",
          name: "Jarvis",
          accent: "primary",
          enabled: true,
          minimized: false,
          sound: false,
          daily_brief: true,
          screen_tips: true,
          notes: [],
          unlocked_characters: ["robot"],
          locked_characters: {},
        }}
        onSave={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Imię asystenta"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
  });
});

describe("internet (21.09)", () => {
  it("źródła to linki zewnętrzne w nowej karcie, bez javascript:", async () => {
    const { JarvisSources } = await import("../JarvisSources");
    render(
      <JarvisSources
        items={[
          { url: "https://example.org/raport", title: "Raport płac IT" },
          { url: "javascript:alert(1)", title: "zły" },
        ]}
      />,
    );
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://example.org/raport");
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0].getAttribute("rel")).toContain("noopener");
  });

  it("przełącznik internetu zmienia podpowiedź i stopkę; niedostępny jest wyłączony", () => {
    const onToggleWeb = vi.fn();
    const { rerender } = render(<JarvisPanel {...panelProps({ onToggleWeb, webMode: false })} />);
    fireEvent.click(screen.getByTestId("jarvis-web-toggle"));
    expect(onToggleWeb).toHaveBeenCalledOnce();

    rerender(<JarvisPanel {...panelProps({ onToggleWeb, webMode: true, webRemaining: 7 })} />);
    expect(screen.getByPlaceholderText("Zapytaj internet…")).toBeInTheDocument();
    expect(screen.getByTestId("jarvis-footnote")).toHaveTextContent("nie widzę danych z NEXUSA");
    expect(screen.getByTestId("jarvis-footnote")).toHaveTextContent("Zostało dziś: 7");

    rerender(
      <JarvisPanel {...panelProps({ onToggleWeb, webUnavailableReason: "Dzisiejszy limit wyczerpany" })} />,
    );
    expect(screen.getByTestId("jarvis-web-toggle")).toBeDisabled();
  });
});


const GUIDE = {
  key: "jobs.board",
  title: "Tablica rekrutacji",
  roles: [],
  what: "Tu prowadzisz kandydatów przez 6 kolumn.",
  tasks: [
    { q: "Jak przesunąć kandydata?", a: "Przeciągnij kartę.", anchor: "jobs.board.columns" },
    { q: "Gdzie są odrzuceni?", a: "Na pasku nad tablicą." },
    { q: "Co to Mój ruch?", a: "Filtr." },
  ],
  pitfalls: ["Uwaga na debrief."],
  anchors: [{ id: "jobs.board.columns", label: "Kolumny", describe: "x" }],
};

describe("przewodnik ekranu", () => {
  it("karta pokazuje zadania, a „Pokaż na ekranie” tylko tam, gdzie jest kotwica", () => {
    const onTask = vi.fn();
    const onShow = vi.fn();
    render(<JarvisGuideCard guide={GUIDE} onTask={onTask} onShow={onShow} />);
    fireEvent.click(screen.getByRole("button", { name: "Gdzie są odrzuceni?" }));
    expect(onTask).toHaveBeenCalledWith(GUIDE.tasks[1]);
    const show = screen.getAllByRole("button", { name: /Pokaż na ekranie/ });
    expect(show).toHaveLength(1);
    fireEvent.click(show[0]);
    expect(onShow).toHaveBeenCalledWith("jobs.board.columns");
    expect(screen.getByText("Uwaga na debrief.")).toBeInTheDocument();
  });

  it("panel ma przycisk „Jak działa ten ekran”, gdy jest przewodnik", () => {
    const onOpenGuide = vi.fn();
    render(<JarvisPanel {...panelProps({ onOpenGuide, guideTitle: "Tablica rekrutacji" })} />);
    fireEvent.click(screen.getByRole("button", { name: "Jak działa ten ekran" }));
    expect(onOpenGuide).toHaveBeenCalled();
  });
});

describe("Zatrzymaj", () => {
  it("w trakcie odpowiedzi zamiast „Wyślij” jest „Zatrzymaj odpowiedź”", () => {
    const onStop = vi.fn();
    render(<JarvisPanel {...panelProps({ streaming: true, onStop })} />);
    expect(screen.queryByRole("button", { name: "Wyślij" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Zatrzymaj odpowiedź" }));
    expect(onStop).toHaveBeenCalled();
  });
});

describe("podświetlenie elementu", () => {
  it("brak elementu na ekranie kończy się onMissing, nie ciszą", () => {
    vi.useFakeTimers();
    const onMissing = vi.fn();
    render(<HelpSpotlight onMissing={onMissing} />);
    act(() => showHelpAnchor("jobs.board.columns"));
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onMissing).toHaveBeenCalledWith("jobs.board.columns");
    vi.useRealTimers();
  });

  it("widoczny element dostaje obrys", () => {
    const onShown = vi.fn();
    const target = document.createElement("div");
    target.setAttribute("data-help", "jobs.board.columns");
    target.getBoundingClientRect = () => ({ top: 10, left: 10, width: 100, height: 40, right: 110, bottom: 50, x: 10, y: 10, toJSON: () => ({}) });
    document.body.appendChild(target);
    render(<HelpSpotlight onShown={onShown} />);
    act(() => showHelpAnchor("jobs.board.columns"));
    expect(onShown).toHaveBeenCalledWith("jobs.board.columns");
    expect(screen.getByTestId("help-spotlight")).toBeInTheDocument();
    target.remove();
  });
});

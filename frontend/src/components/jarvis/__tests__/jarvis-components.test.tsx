import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JarvisActionCard } from "../JarvisActionCard";
import { JarvisMarkdown } from "../JarvisMarkdown";
import { JarvisPanel, type JarvisPanelProps } from "../JarvisPanel";

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

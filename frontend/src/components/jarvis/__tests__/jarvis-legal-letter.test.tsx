import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { applyStreamEvent, type JarvisTurnState } from "@/lib/jarvis/reducer";
import type { JarvisLegalLetter } from "@/lib/jarvis/types";

import { JarvisLegalLetterCard, legalLetterHref } from "../JarvisLegalLetterCard";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const LETTER: JarvisLegalLetter = {
  contract_id: 12,
  kind: "notice_reply",
  label: "Odpowiedź na wypowiedzenie Partnera",
  subject: "potwierdzenie wypowiedzenia umowy nr 41/2025",
  text: "Szanowny Panie,\n\npotwierdzamy …",
  blocked: true,
  block_reasons: ["Odpowiedz na pytanie o formę wypowiedzenia."],
  lawyer_review: [],
  counts: { ok: 2, missing: 0, mismatch: 0 },
};

describe("szkic pisma od Jarvisa", () => {
  it("karta mówi, że nic nie wysłano, i prowadzi do panelu pisma", () => {
    render(<JarvisLegalLetterCard letter={LETTER} />);
    expect(screen.getByTestId("jarvis-legal-letter")).toHaveTextContent("Szkic pisma — nic nie wysłano");
    expect(screen.getByRole("link", { name: "Otwórz panel pisma" })).toHaveAttribute(
      "href",
      "/contracts/12?pismo=notice_reply",
    );
    expect(screen.getByText(/Do poprawy przed zatwierdzeniem/)).toBeInTheDocument();
    expect(screen.getByText("2 z 2 cytatów sprawdzone · nic nie wysłano")).toBeInTheDocument();
  });

  it("karta z historii (bez treści) i nieznany rodzaj", () => {
    expect(legalLetterHref({ contract_id: 3, kind: "x" })).toBe("/contracts/3?pismo=1");
    render(<JarvisLegalLetterCard letter={{ contract_id: 3, kind: "termination_notice" }} />);
    expect(screen.getByText("Wypowiedzenie umowy przez B2B.net")).toBeInTheDocument();
  });

  it("zdarzenie strumienia dokłada kartę", () => {
    const state = { items: [] } as unknown as JarvisTurnState;
    const next = applyStreamEvent(state, { type: "legal_letter", letter: LETTER });
    expect(next.items.at(-1)).toEqual({ kind: "legal_letter", letter: LETTER });
  });
});

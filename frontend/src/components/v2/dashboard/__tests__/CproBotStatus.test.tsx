import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { CproBotItemStatus, CproBotLine, cproBotText, cproOfferHref } from "../CproBotStatus";
import type { CproBotItem } from "@/lib/api/boardTasks";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

function bot(over: Partial<CproBotItem>): CproBotItem {
  return {
    state: "ready",
    blockers: [],
    message: null,
    offer_url: null,
    cpro_status: null,
    at: null,
    moved: null,
    data_from: [],
    ...over,
  };
}

function wrap(node: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);
}

describe("cproBotText", () => {
  it("lists every blocker so the person knows what to fill in NEXUS", () => {
    const { tone, text } = cproBotText(
      bot({ state: "blocked", blockers: ["Brak narodowości w Warunkach", "Brak stawki do Cpro"] }),
    );
    expect(tone).toBe("warning");
    expect(text).toBe("Bot czeka: Brak narodowości w Warunkach · Brak stawki do Cpro");
  });

  it("asks for a manual move when the bot sent but the card stayed", () => {
    const { tone, text } = cproBotText(bot({ state: "submitted", moved: false, cpro_status: "SELECTION" }));
    expect(tone).toBe("warning");
    expect(text).toContain("kliknij „Wrzucone”");
    expect(cproBotText(bot({ state: "submitted", moved: true })).tone).toBe("success");
  });

  it("shows the bot's reason on failure", () => {
    expect(cproBotText(bot({ state: "failed", message: "Request zamknięty." })).text).toBe(
      "Bot nie wrzucił: Request zamknięty. Wrzuć ręcznie albo ponów.",
    );
  });
});

describe("cproOfferHref", () => {
  it("keeps only https links", () => {
    expect(cproOfferHref("https://nordea.onevms.se/x")).toBe("https://nordea.onevms.se/x");
    expect(cproOfferHref("javascript:alert(1)")).toBeUndefined();
    expect(cproOfferHref(null)).toBeUndefined();
  });
});

describe("CproBotItemStatus", () => {
  it("renders nothing when the bot is off", () => {
    const { container } = wrap(<CproBotItemStatus stageId={1} bot={null} canRetry />);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers retry only for failed cards and only to people who may move them", () => {
    const failed = bot({ state: "failed", message: "x", data_from: ["42480"] });
    const { rerender } = wrap(<CproBotItemStatus stageId={1} bot={failed} canRetry />);
    expect(screen.getByRole("button", { name: /Ponów botem/ })).toBeInTheDocument();
    expect(screen.getByText("Dane z rekrutacji 42480")).toBeInTheDocument();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <CproBotItemStatus stageId={1} bot={failed} canRetry={false} />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole("button", { name: /Ponów botem/ })).not.toBeInTheDocument();
  });

  it("links the offer in Cpro after sending", () => {
    wrap(
      <CproBotItemStatus
        stageId={1}
        bot={bot({ state: "submitted", moved: true, offer_url: "https://nordea.onevms.se/o/1" })}
        canRetry
      />,
    );
    expect(screen.getByRole("link", { name: /Oferta w Cpro/ })).toHaveAttribute("href", "https://nordea.onevms.se/o/1");
    expect(screen.queryByRole("button", { name: /Ponów botem/ })).not.toBeInTheDocument();
  });
});

describe("CproBotLine", () => {
  it("tells to work manually while the routine is missing", () => {
    wrap(<CproBotLine bot={{ configured: false, working: false, last_run_at: null, sent_today: 0, can_retry: true }} />);
    expect(screen.getByTestId("cpro-bot-line")).toHaveTextContent("wrzucaj ręcznie");
  });

  it("summarises the day", () => {
    wrap(<CproBotLine bot={{ configured: true, working: true, last_run_at: null, sent_today: 3, can_retry: true }} />);
    expect(screen.getByTestId("cpro-bot-line")).toHaveTextContent("Bot Cpro · wypełnia Cpro teraz · wysłane dziś: 3");
  });
});

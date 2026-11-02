/** Spotkania: transkrypt widać tylko po pobraniu, podsumowanie zastępuje podgląd notatki. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Meeting } from "@/lib/api/sales";

const baseMeeting = {
  id: 1,
  kind: "meeting",
  subject: "Warsztat z klientem",
  body: "Notatka z Outlooka",
  occurred_at: "2026-10-22T10:00:00Z",
  created_at: "2026-10-22T10:00:00Z",
  company: { id: 7, name: "Firma" },
  opportunity: null,
  external_source: "msgraph-event",
  transcript_status: null,
  transcript_summary: null,
} as unknown as Meeting;

let items: Meeting[] = [];

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/sales/meetings",
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useSalesMeetings: () => ({
    data: { items, total: items.length },
    isLoading: false,
    error: null,
    isSuccess: true,
    refetch: vi.fn(),
  }),
  useMeetingTranscript: () => ({
    data: { subject: "Warsztat z klientem", summary: "Ustalono demo.", plain_text: "Handlowiec: Dzień dobry" },
    isLoading: false,
    error: null,
    isSuccess: true,
    refetch: vi.fn(),
  }),
}));

import { MeetingsView } from "../MeetingsView";

describe("Spotkania", () => {
  it("bez transkryptu pokazuje notatkę i nie obiecuje transkryptu", () => {
    items = [{ ...baseMeeting, transcript_status: "missing" }];
    render(<MeetingsView />);
    expect(screen.getByText("Notatka z Outlooka")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Czytaj transkrypt" })).toBeNull();
  });

  it("po pobraniu pokazuje podsumowanie i otwiera pełny tekst", () => {
    items = [{ ...baseMeeting, transcript_status: "fetched", transcript_summary: "Krótko: demo." }];
    render(<MeetingsView />);
    expect(screen.getByText("Krótko: demo.")).toBeInTheDocument();
    expect(screen.queryByText("Notatka z Outlooka")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Czytaj transkrypt" }));
    expect(screen.getByText("Handlowiec: Dzień dobry")).toBeInTheDocument();
    expect(screen.getByText("Ustalono demo.")).toBeInTheDocument();
  });
});

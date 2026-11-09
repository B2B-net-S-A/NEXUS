import { describe, expect, it } from "vitest";

import type { OwnHiringCard } from "@/lib/api/ownHiring";

import { cardStatus, formatDueDay, formatMonths } from "../format";
import { parseWindows } from "../SettingsView";

const card = (over: Partial<OwnHiringCard>): OwnHiringCard => ({
  id: 1,
  candidate_id: 1,
  name: "Testowa Osoba",
  city: null,
  stage: "new",
  bucket: "match",
  filter_reason: "role",
  role: "IT Recruiter",
  company: "Firma",
  months: 14,
  until: null,
  is_it: true,
  source: "Pracuj.pl",
  ad_title: "IT Recruiter",
  applied_at: "2026-11-09T08:00:00Z",
  has_email: true,
  invited_at: null,
  response_due_at: null,
  replied_at: null,
  call_attempts: 0,
  callback_at: null,
  booking: null,
  needs_decision: false,
  contract_sent_at: null,
  signed_at: null,
  close_reason: null,
  ...over,
});

const NOW = new Date("2026-11-09T12:00:00Z");

describe("formatMonths", () => {
  it.each([
    [null, "bez dat"],
    [0, "bez dat"],
    [7, "7 mies."],
    [12, "1 r."],
    [14, "1 r. 2 mies."],
    [36, "3 l."],
  ])("%s → %s", (months, label) => {
    expect(formatMonths(months)).toBe(label);
  });
});

describe("formatDueDay", () => {
  it("pokazuje ostatni dzień, nie północ po nim", () => {
    expect(formatDueDay("2026-11-13T23:00:00Z")).toBe("13.11");
  });
});

describe("cardStatus", () => {
  it("oznacza ostatni dzień na odpowiedź", () => {
    const status = cardStatus(
      card({ stage: "invited", response_due_at: "2026-11-10T02:00:00Z" }),
      NOW,
    );
    expect(status).toMatchObject({ badge: "Ostatni dzień", tone: "warning" });
  });

  it("odpowiedź mailem wygrywa z licznikiem", () => {
    const status = cardStatus(
      card({
        stage: "invited",
        replied_at: "2026-11-09T09:00:00Z",
        response_due_at: "2026-11-10T02:00:00Z",
      }),
      NOW,
    );
    expect(status.tone).toBe("info");
  });

  it("po rozmowie wymaga decyzji", () => {
    expect(cardStatus(card({ stage: "teams", needs_decision: true }), NOW).badge).toBe(
      "Wpisz decyzję",
    );
  });

  it("pokazuje numer próby telefonu", () => {
    expect(cardStatus(card({ stage: "assistant", call_attempts: 1 }), NOW).badge).toBe(
      "Próba 2 z 3",
    );
  });

  it("niezałożone spotkanie jest widoczne na karcie", () => {
    const status = cardStatus(
      card({
        stage: "teams",
        booking: {
          kind: "teams",
          start: "2026-11-12T09:00:00Z",
          end: "2026-11-12T09:30:00Z",
          via: "link",
          sync_status: "failed",
          join_url: null,
        },
      }),
      NOW,
    );
    expect(status).toMatchObject({ badge: "Spotkanie do założenia", tone: "warning" });
  });
});

describe("parseWindows", () => {
  it("czyta kilka okien i uzupełnia zero", () => {
    expect(parseWindows("9:00-11:00, 13:00 - 14:30")).toEqual([
      ["09:00", "11:00"],
      ["13:00", "14:30"],
    ]);
  });

  it("puste pole to dzień bez rozmów", () => {
    expect(parseWindows("  ")).toEqual([]);
  });

  it("odrzuca błędny zapis", () => {
    expect(parseWindows("rano")).toBeNull();
  });
});

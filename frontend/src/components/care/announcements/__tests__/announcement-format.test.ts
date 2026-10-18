import { describe, expect, it } from "vitest";

import type { AnnouncementRow } from "@/lib/api/care-announcements";

import {
  PLACEHOLDERS,
  normalizeBody,
  normalizeSubject,
  recipientStatusLabel,
  sendBlocker,
  sendMinutes,
  statusView,
  unknownPlaceholders,
} from "../announcement-format";

function row(overrides: Partial<AnnouncementRow> = {}): AnnouncementRow {
  return {
    id: 7,
    marker: "[Komunikat 7/AB12]",
    kind: "mandatory",
    status: "sent",
    subject: "Od listopada faktury do 5. dnia miesiąca",
    author: { id: 1, name: "Natalia Opiekuńcza" },
    audience: { group: "all" },
    audience_label: "wszyscy aktywni konsultanci",
    recipient_count: 124,
    requires_approval: true,
    approver: null,
    created_at: null,
    submitted_at: null,
    approved_at: null,
    queued_at: null,
    send_started_at: null,
    send_finished_at: "2026-10-10T09:09:00+00:00",
    cancelled_at: null,
    counts: {
      pending: 0,
      sending: 0,
      sent: 117,
      failed: 0,
      uncertain: 0,
      bounced: 2,
      excluded_no_email: 2,
      excluded_opted_out: 5,
      cancelled: 0,
      unsubscribed: 1,
    },
    replies: { reply: 23, bounce: 2 },
    can_approve: false,
    ...overrides,
  };
}

describe("pola w treści", () => {
  it("zna tylko {imię} i {opiekun}", () => {
    expect(PLACEHOLDERS).toEqual(["{imię}", "{opiekun}"]);
    expect(unknownPlaceholders("Cześć {imię}, pisz do {opiekun}.")).toEqual([]);
    expect(unknownPlaceholders("Cześć {imie} {nazwisko} {imie}")).toEqual(["{imie}", "{nazwisko}"]);
  });
});

describe("stan komunikatu", () => {
  it("czekający na zatwierdzenie mówi do zatwierdzającego „na Twoje”", () => {
    expect(statusView(row({ status: "pending", can_approve: true })).label).toBe(
      "czeka na Twoje zatwierdzenie",
    );
    expect(statusView(row({ status: "pending" })).label).toBe("czeka na zatwierdzenie");
  });

  it("wysłany liczy wysłane i odbite, w kolejce — pozostałe osoby", () => {
    const sent = statusView(row());
    expect(sent.tone).toBe("success");
    expect(sent.note).toBe("117 wysłanych, 2 odbite");
    const queued = statusView(
      row({ status: "queued", counts: { ...row().counts, pending: 40, sent: 84, bounced: 0 } }),
    );
    expect(queued.label).toBe("w kolejce");
    expect(queued.note).toBe("84 wysłane, 40 czeka");
  });

  it("błędy wysyłki są widoczne w drobnym druku", () => {
    const view = statusView(row({ counts: { ...row().counts, failed: 3, uncertain: 1, bounced: 0 } }));
    expect(view.tone).toBe("warning");
    expect(view.note).toBe("117 wysłanych, 4 błędy");
  });
});

describe("tempo kolejki", () => {
  it("30 maili na minutę, zaokrąglone w górę", () => {
    expect(sendMinutes(124, 30)).toBe(5);
    expect(sendMinutes(1, 30)).toBe(1);
    expect(sendMinutes(0, 30)).toBe(0);
  });
});

describe("dlaczego nie można wysłać", () => {
  const base = {
    saved: true,
    contentDirty: false,
    testCurrent: true,
    willReceive: 3,
    sendingEnabled: true,
    requiresApproval: false,
  };

  it("kolejno: zapis, próba, odbiorcy, przełącznik", () => {
    expect(sendBlocker({ ...base, saved: false })).toMatch(/próbnie/);
    expect(sendBlocker({ ...base, contentDirty: true })).toMatch(/próbnie/);
    expect(sendBlocker({ ...base, testCurrent: false })).toMatch(/próbnie/);
    expect(sendBlocker({ ...base, willReceive: 0 })).toMatch(/Nikt/);
    expect(sendBlocker({ ...base, sendingEnabled: false })).toMatch(/wyłączona/);
    expect(sendBlocker(base)).toBeNull();
  });

  it("do zatwierdzenia można wysłać mimo wyłączonej wysyłki", () => {
    expect(sendBlocker({ ...base, sendingEnabled: false, requiresApproval: true })).toBeNull();
  });
});

describe("stan osoby na liście", () => {
  it("wykluczenia mówią dlaczego", () => {
    expect(recipientStatusLabel("excluded_no_email")).toBe("bez adresu e-mail");
    expect(recipientStatusLabel("excluded_opted_out")).toBe("wypis z informacyjnych");
    expect(recipientStatusLabel("pending")).toBe("dostanie");
  });
});

describe("normalizeSubject / normalizeBody (lustro zapisu serwera)", () => {
  it("każdy ciąg białych znaków w temacie to jedna spacja", () => {
    expect(normalizeSubject("  Ankieta\u00a0o  sprzęcie\tod\nklienta  ")).toBe(
      "Ankieta o sprzęcie od klienta",
    );
    expect(normalizeSubject("Te\0mat")).toBe("Temat");
    expect(normalizeSubject(" \u00a0 ")).toBe("");
  });

  it("treść: bez NUL, CRLF → LF, bez białych znaków na brzegach; środek zostaje", () => {
    expect(normalizeBody("\r\nCześć {imię},\r\n\r\n  akapit  \n")).toBe(
      "Cześć {imię},\n\n  akapit",
    );
  });
});

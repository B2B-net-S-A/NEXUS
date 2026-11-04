import { afterEach, describe, expect, it } from "vitest";

import type { M365ConnectionStatus } from "@/lib/api";
import { isAllowedReturnPath, rememberM365Return, takeM365Return } from "@/lib/m365-return";

import { mailboxNotice } from "../SalesMailboxStatus";

const status = (patch: Partial<M365ConnectionStatus>): M365ConnectionStatus => ({
  connected: false,
  mail_to_sales: true,
  ...patch,
});

describe("mailboxNotice", () => {
  it("hides the strip when the mailbox does not feed Sales", () => {
    expect(mailboxNotice(undefined)).toBe("hidden");
    expect(mailboxNotice(status({ mail_to_sales: false, connected: true }))).toBe("hidden");
  });

  it("asks to connect, reconnect or reports the sync state", () => {
    expect(mailboxNotice(status({}))).toBe("connect");
    expect(mailboxNotice(status({ requires_reconnect: true }))).toBe("reconnect");
    expect(mailboxNotice(status({ connected: true }))).toBe("connected");
    expect(mailboxNotice(status({ connected: true, last_error: "timeout" }))).toBe("error");
  });
});

describe("m365 return path", () => {
  afterEach(() => window.sessionStorage.clear());

  it("returns to Sales only for internal Sales paths", () => {
    expect(isAllowedReturnPath("/sales")).toBe(true);
    expect(isAllowedReturnPath("/sales/companies/12")).toBe(true);
    expect(isAllowedReturnPath("/salesforce")).toBe(false);
    expect(isAllowedReturnPath("//evil.example/sales")).toBe(false);
    expect(isAllowedReturnPath("https://evil.example/sales")).toBe(false);
    expect(isAllowedReturnPath("/settings")).toBe(false);
  });

  it("remembers the Sales screen once and falls back to Settings", () => {
    rememberM365Return("/sales/companies");
    expect(takeM365Return()).toBe("/sales/companies");
    expect(takeM365Return()).toBe("/settings");
    rememberM365Return("https://evil.example");
    expect(takeM365Return()).toBe("/settings");
  });
});

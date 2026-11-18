import { describe, expect, it } from "vitest";

import type { PanelPreview, SettlementsStart } from "@/lib/api/client-settlements";
import { PANEL_STATE_OPTIONS, panelOpenForConsultants } from "@/lib/api/consultant-panel";
import { portalKeys } from "@/lib/api/consultant-portal";

import { previewClient } from "../PanelPreviewDialog";
import { startChecks } from "../SettlementsStartCard";

const start: SettlementsStart = {
  module_enabled: true,
  portal_state: "internal",
  back_office: true,
  mailbox: { configured: true, last_run_at: null, last_status: null, last_error: null },
  rule_clients: [],
  active_panels: 0,
};

const byKey = (data: SettlementsStart) => Object.fromEntries(startChecks(data).map((c) => [c.key, c]));

describe("Tylko zespół: stan panelu", () => {
  it("nie otwiera panelu konsultantom", () => {
    expect(panelOpenForConsultants("internal")).toBe(false);
    expect(panelOpenForConsultants("off")).toBe(false);
    expect(panelOpenForConsultants("pilot")).toBe(true);
    expect(panelOpenForConsultants("all")).toBe(true);
  });

  it("ma cztery stany w kolejności od zamkniętego", () => {
    expect(PANEL_STATE_OPTIONS.map((o) => o.value)).toEqual(["off", "internal", "pilot", "all"]);
  });
});

describe("Karta „Start rozliczeń”", () => {
  it("w trybie „Tylko zespół” mówi, że konsultanci nic nie dostają", () => {
    expect(byKey(start).panels).toMatchObject({ tone: "success" });
    expect(byKey(start).panels.text).toContain("zero maili");
  });

  it("ostrzega, gdy przyjęcie RCP zdejmuje MD u klienta z regułami", () => {
    const checks = byKey({
      ...start,
      rule_clients: [
        { client_id: 12, name: "Klient A", effective_from: "2026-11", md_charged_on_accept: true },
        { client_id: 13, name: "Klient B", effective_from: "2026-11", md_charged_on_accept: false },
      ],
    });
    expect(checks.md).toMatchObject({ tone: "warning" });
    expect(checks.md.text).toContain("Klient A");
    expect(checks.md.text).not.toContain("Klient B");
  });

  it("pokazuje błąd dostępu do skrzynki z kodem", () => {
    const checks = byKey({
      ...start,
      mailbox: { configured: true, last_run_at: null, last_status: "error", last_error: "http_403" },
    });
    expect(checks.mailbox).toMatchObject({ tone: "danger" });
    expect(checks.mailbox.text).toContain("http_403");
  });

  it("wspólna skrzynka bez adresu rozliczeń to brak konfiguracji, nie brak dostępu", () => {
    const checks = byKey({
      ...start,
      mailbox: { configured: true, last_run_at: null, last_status: "error", last_error: "shared_without_route" },
    });
    expect(checks.mailbox).toMatchObject({ tone: "danger" });
    expect(checks.mailbox.text).toContain("brak adresu rozliczeń");
    expect(checks.mailbox.note).not.toContain("Mail.Read");
  });

  it("panel dla konsultantów i wyłączony moduł to stany do poprawy", () => {
    const checks = byKey({ ...start, module_enabled: false, back_office: false, portal_state: "pilot", active_panels: 3 });
    expect(checks.module.tone).toBe("danger");
    expect(checks.bo.tone).toBe("danger");
    expect(checks.panels).toMatchObject({ tone: "warning" });
    expect(checks.panels.text).toContain("3");
  });
});

describe("Podgląd panelu", () => {
  it("wkłada dane pod klucze panelu, więc ekrany niczego nie pobierają", () => {
    const data = {
      activated: false,
      me: { first_name: "Jan" },
      todo: { items: [] },
      settlement: { mode: null },
      finance: { months: [] },
    } as unknown as PanelPreview;
    const client = previewClient(data);
    expect(client.getQueryData(portalKeys.me)).toBe(data.me);
    expect(client.getQueryData(portalKeys.finance)).toBe(data.finance);
    expect(client.getQueryData(portalKeys.meetings)).toEqual({ items: [], note: "" });
    expect(client.getDefaultOptions().queries?.staleTime).toBe(Infinity);
  });
});

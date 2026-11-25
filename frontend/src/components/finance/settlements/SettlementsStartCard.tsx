"use client";

// Karta „Start rozliczeń” nad zakładką Rozliczenia, tylko dla admina (decyzja Artura
// 16.11.2026, tryb „Tylko zespół”): włącznik modułu, stan panelu konsultanta i lista
// tego, czego brakuje do startu. Zapisy idą przez trasy przełączników; serwer
// sprawdza admina, więc dla innych kont karty po prostu nie ma (403 → nic).
import { useQueryClient } from "@tanstack/react-query";

import { StatusDot, type StatusDotTone } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  settlementKeys,
  useSetSettlementsModule,
  useSettlementsStart,
  type SettlementsStart,
} from "@/lib/api/client-settlements";
import {
  PANEL_STATE_OPTIONS,
  useSavePanelSwitches,
  type PanelState,
} from "@/lib/api/consultant-panel";
import { hasRole, useAuthStore } from "@/store/auth";

import { FeedbackSwitch, ReportReminderSwitch } from "./ReportReminders";

interface Check {
  key: string;
  tone: StatusDotTone;
  text: string;
  note?: string;
}

function mailboxCheck(start: SettlementsStart): Check {
  const box = start.mailbox;
  if (!box.configured) {
    return {
      key: "mailbox",
      tone: "danger",
      text: "Skrzynka dla czytnika rozliczeń nie jest ustawiona",
      note: "zmienna skrzynki",
    };
  }
  if (box.last_status === "ok" || box.last_status === "partial") {
    return {
      key: "mailbox",
      tone: "success",
      text: "Czytnik rozliczeń działa",
    };
  }
  if (box.last_status === "error" && box.last_error === "shared_without_route") {
    return {
      key: "mailbox",
      tone: "danger",
      text: "Skrzynka rozliczeń jest wspólna ze sprawami, a brak adresu rozliczeń",
      note: "zmienna adresów rozliczeń (E8)",
    };
  }
  if (box.last_status === "error" && box.last_error === "route_not_shared") {
    return {
      key: "mailbox",
      tone: "danger",
      text: "Adres rozliczeń ustawiony, ale skrzynka spraw jest inna niż skrzynka rozliczeń",
      note: "skrzynka spraw = skrzynka rozliczeń (E8)",
    };
  }
  if (box.last_status === "error") {
    return {
      key: "mailbox",
      tone: "danger",
      text: `Czytnik rozliczeń nie ma dostępu (${box.last_error ?? "błąd"})`,
      note: "M365: Mail.Read dla „NEXUS Kadry”",
    };
  }
  return {
    key: "mailbox",
    tone: "warning",
    text: "Czytnik rozliczeń jeszcze nie ruszył",
    note: "rusza co 15 min po włączeniu",
  };
}

export function startChecks(start: SettlementsStart): Check[] {
  const charging = start.rule_clients.filter((c) => c.md_charged_on_accept);
  return [
    start.module_enabled
      ? { key: "module", tone: "success", text: "Moduł rozliczeń włączony" }
      : {
          key: "module",
          tone: "danger",
          text: "Moduł rozliczeń wyłączony: Finanse nie widzą zakładki",
        },
    start.back_office
      ? { key: "bo", tone: "success", text: "Back office włączony" }
      : {
          key: "bo",
          tone: "danger",
          text: "Back office wyłączony: „Tylko zespół” i „Wszyscy” działają jak wyłączony panel",
          note: "Ustawienia → Kadry → Moduły",
        },
    mailboxCheck(start),
    start.rule_clients.length
      ? {
          key: "rules",
          tone: "success",
          text: `Reguły zapisane: ${start.rule_clients.map((c) => c.name).join(", ")}`,
        }
      : {
          key: "rules",
          tone: "warning",
          text: "Żaden klient nie ma reguł: pliki wchodzą bez kontroli",
          note: "Reguły klienta",
        },
    charging.length
      ? {
          key: "md",
          tone: "warning",
          text: `Przyjęcie RCP zdejmuje MD z zamówienia: ${charging.map((c) => c.name).join(", ")}`,
          note: "na czas testów reguła „Zejście z zamówienia” = Wyłączone",
        }
      : {
          key: "md",
          tone: "success",
          text: "Przyjęcie RCP nie zmienia zużycia MD",
        },
    start.portal_state === "pilot" || start.portal_state === "all"
      ? {
          key: "panels",
          tone: "warning",
          text: `Konsultanci mają dostęp: aktywnych paneli ${start.active_panels}`,
        }
      : {
          key: "panels",
          tone: "success",
          text: "Konsultanci nic nie dostają: panel zamknięty, zero maili",
        },
  ];
}

export function SettlementsStartCard() {
  // `GET …/settlements/start` jest tylko dla admina; Finanse dostawały 403 w konsoli.
  const isAdmin = useAuthStore((state) => hasRole(state.user, "admin"));
  const start = useSettlementsStart(isAdmin);
  const setModule = useSetSettlementsModule();
  const savePanel = useSavePanelSwitches();
  const client = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();

  if (!start.isSuccess) return null;
  const data = start.data;

  const toggleModule = async (next: boolean) => {
    const ok = await askConfirm({
      title: next ? "Włączyć moduł rozliczeń?" : "Wyłączyć moduł rozliczeń?",
      description: next
        ? "Finanse zobaczą zakładkę Rozliczenia, a NEXUS zacznie zapisywać faktury kontraktorów z KSeF. Nikt spoza firmy nic nie dostaje."
        : "Finanse stracą zakładkę Rozliczenia. Dane zostają.",
      confirmLabel: "Tak",
      cancelLabel: "Zostaw",
    });
    if (!ok) return;
    try {
      await setModule.mutateAsync(next);
    } catch (failure) {
      showToast(
        apiErrorMessage(failure, "Nie udało się zapisać włącznika."),
        "error",
      );
    }
  };

  const pickState = async (next: PanelState) => {
    const option = PANEL_STATE_OPTIONS.find((o) => o.value === next);
    if (!option || next === data.portal_state) return;
    const ok = await askConfirm({
      title: `Panel konsultanta: ${option.label}?`,
      description: option.confirm,
      confirmLabel: "Tak",
      cancelLabel: "Zostaw",
    });
    if (!ok) return;
    try {
      await savePanel.mutateAsync({ state: next });
      await client.invalidateQueries({ queryKey: settlementKeys.start });
    } catch (failure) {
      showToast(
        apiErrorMessage(failure, "Nie udało się zapisać stanu panelu."),
        "error",
      );
    }
  };

  return (
    <section
      aria-labelledby="settlements-start"
      className="space-y-3 rounded-xl border bg-card p-4"
    >
      {confirmDialog}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="settlements-start" className="text-sm font-semibold">
          Start rozliczeń
        </h2>
        <span className="text-xs text-muted-foreground">
          widzi tylko administrator
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <label className="flex items-center gap-2">
          <Switch
            checked={data.module_enabled}
            disabled={setModule.isPending}
            onCheckedChange={toggleModule}
          />
          Moduł rozliczeń klientów
        </label>
        <ReportReminderSwitch />
        <FeedbackSwitch />
        <span className="flex flex-wrap items-center gap-2">
          <span id="start-panel-state">Panel konsultanta</span>
          <SegmentedRadio
            labelledBy="start-panel-state"
            size="sm"
            value={data.portal_state}
            disabled={savePanel.isPending}
            options={PANEL_STATE_OPTIONS.map(({ value, label }) => ({
              value,
              label,
            }))}
            onChange={(next) => void pickState(next)}
          />
        </span>
      </div>
      <ul className="divide-y divide-border text-sm">
        {startChecks(data).map((check) => (
          <li
            key={check.key}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5"
          >
            <StatusDot tone={check.tone}>{check.text}</StatusDot>
            {check.note ? (
              <span className="text-xs text-muted-foreground">
                {check.note}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

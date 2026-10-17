"use client";

/**
 * Harness „Mój czas” (makiety 2 „Wniosek urlopowy” i 4 „Mój miesiąc” raportu
 * „Ludzie w NEXUSIE”).
 *
 * Prawdziwy `MyTimeScreen` (zakładki Urlopy, Mój miesiąc, Premie, Kartoteka)
 * na zasianym cache, ZERO zapytań (`hr-harness.tsx`). Zakładkę wybiera sam
 * ekran z adresu (`?tab=`), miesiąc to bieżący miesiąc przeglądarki.
 *
 * Stany:
 * - `?tab=leave` (domyślnie) — urlopy Oli: saldo, wnioski (zatwierdzony
 *   z przekierowaniem poczty, wpisany, odrzucony z powodem);
 * - `?state=request` — Kamil (Delivery Lead) z otwartym oknem „Wniosek
 *   o nieobecność”: zastępca proponowany, „Co wypada w tym czasie” (rozmowy
 *   u klienta, prep, screening), nieobecni z działu, saldo po wniosku. Okno
 *   startuje od dziś (tak działa ekran) — podgląd jest zasiany dla „bez
 *   zastępcy” i każdego zastępcy z listy, więc wybór nie wysyła zapytania.
 *   W weekend serwer odpowiada „W wybranym okresie nie ma dni roboczych.” —
 *   harness pokazuje to samo;
 * - `?tab=month` — „Mój miesiąc” Oli: dni do wczoraj wpisane, urlop z wniosku,
 *   nadgodzina, dziś pusty dzień z podpowiedzią opisu („+” przy dniu), jutro
 *   zaplanowane zdalnie; poprzedni miesiąc zaakceptowany (strzałka „‹”);
 * - `?tab=bonuses` — premie Oli (przyznane i jedna „liczy się”).
 */

import { useState } from "react";

import { LeaveRequestDialog } from "@/components/hr/leave/LeaveRequestDialog";
import { warsawToday } from "@/components/hr/leave/leave-format";
import { MyTimeScreen } from "@/components/hr/MyTimeScreen";
import { currentYearMonth, shiftMonth } from "@/components/hr/time/time-format";
import { equipmentKeys } from "@/lib/api/equipment";
import { leaveKeys, type LeaveInput } from "@/lib/api/hr-leave";
import { payrollKeys } from "@/lib/api/hr-payroll";
import { timeKeys } from "@/lib/api/hr-time";

import { HR_CAST, HR_CONFIG_QUERY_KEY, harnessMonthDays, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import {
  KAMIL_SUBSTITUTES,
  MY_EQUIPMENT,
  TEMPLATES,
  balance,
  dayHint,
  kamilPreview,
  kamilRequests,
  myProfile,
  olaMonth,
  olaPayroll,
  olaRequests,
} from "./fixtures";

const STATES = ["leave", "request", "month", "bonuses"] as const;
type State = (typeof STATES)[number];

const LINKS = [
  { key: "leave", label: "Urlopy", href: "?tab=leave" },
  { key: "request", label: "Wniosek urlopowy (Kamil)", href: "?state=request&tab=leave" },
  { key: "month", label: "Mój miesiąc", href: "?tab=month" },
  { key: "bonuses", label: "Premie", href: "?tab=bonuses" },
] as const;

function prepare(params: URLSearchParams) {
  const state: State =
    params.get("state") === "request"
      ? "request"
      : pickState(params.get("tab"), STATES, "leave");
  const viewer = state === "request" ? HR_CAST.kamil : HR_CAST.ola;
  const today = warsawToday();
  const current = currentYearMonth();
  const year = current.year;
  const client = harnessQueryClient();
  const config = hrConfig();

  client.setQueryData(HR_CONFIG_QUERY_KEY, config);
  client.setQueryData(["hr", "me"], myProfile(viewer, year));
  client.setQueryData(equipmentKeys.me, MY_EQUIPMENT);

  // Urlopy
  if (state === "request") {
    client.setQueryData(leaveKeys.balance(year), balance(year, "9.5", "18.5"));
    client.setQueryData(leaveKeys.mine, kamilRequests(current));
    client.setQueryData(leaveKeys.substitutes("self", today, today), KAMIL_SUBSTITUTES);
    for (const substitute of [null, ...KAMIL_SUBSTITUTES.map((row) => row.user_id)]) {
      const input: LeaveInput = {
        leave_type: "vacation",
        start_date: today,
        end_date: today,
        half_day: null,
        substitute_user_id: substitute,
      };
      client.setQueryData(leaveKeys.preview("self", input), kamilPreview(today, substitute));
    }
  } else {
    client.setQueryData(leaveKeys.balance(year), balance(year, "11.5", "16.5"));
    client.setQueryData(leaveKeys.mine, olaRequests(current));
  }

  // Mój miesiąc: bieżący (szkic), poprzedni (zaakceptowany), następny (pusty).
  client.setQueryData(timeKeys.month(current.year, current.month), olaMonth(current, today, false));
  const previous = shiftMonth(current, -1);
  client.setQueryData(timeKeys.month(previous.year, previous.month), olaMonth(previous, today, true));
  const next = shiftMonth(current, 1);
  client.setQueryData(timeKeys.month(next.year, next.month), olaMonth(next, today, false));
  client.setQueryData(timeKeys.templates, TEMPLATES);
  const monthIso = `${current.year}-${String(current.month).padStart(2, "0")}`;
  for (const day of harnessMonthDays(monthIso)) {
    client.setQueryData(timeKeys.hint(day.date), dayHint(day.date, today));
  }

  // Premie
  client.setQueryData(payrollKeys.me, olaPayroll(current));

  return { user: viewer, client, value: { state, config } };
}

export default function HrMyTimePreviewPage() {
  const ready = useHrHarness(prepare);
  const [dialogOpen, setDialogOpen] = useState(true);
  if (!ready) return <HrHarnessLoading />;
  const { state, config } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Mój czas"
      note={
        state === "request"
          ? "Kamil Testowy (Delivery Lead) składa wniosek. Dane fikcyjne, bez zapytań."
          : "Ola Przykładowa (rekruterka, B2B). Dane fikcyjne, bez zapytań."
      }
      states={LINKS}
      current={state}
    >
      <MyTimeScreen config={config} />
      {state === "request" ? (
        <LeaveRequestDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          mode="self"
          allowedTypes={["vacation"]}
        />
      ) : null}
    </HrHarnessShell>
  );
}

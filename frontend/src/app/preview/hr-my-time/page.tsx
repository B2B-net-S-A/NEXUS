"use client";

/**
 * Harness „Mój czas” (makiety 2 „Wniosek urlopowy” i 4 „Mój miesiąc” raportu
 * „Ludzie w NEXUSIE”).
 *
 * Prawdziwy `MyTimeScreen` (zakładki Przegląd, Urlopy, Mój miesiąc, Premie
 * i stawka; kartoteka w karcie „Ja w firmie”) na zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 * Zakładkę wybiera sam ekran z adresu (`?tab=`), miesiąc to bieżący miesiąc
 * przeglądarki. Forma zatrudnienia Oli: `?form=` (domyślnie B2B z umowną pulą
 * płatnych dni; `uop` — urlop z limitami Kodeksu; `zlecenie` — bez puli).
 *
 * Stany:
 * - `?tab=overview` (domyślnie) — „Przegląd” (etap 2): nieobecności rozbite na
 *   wykorzystane/zaplanowane/czeka, miesiąc z nazwą zależną od formy, premie
 *   w drodze (prognoza z podpisanej umowy i propozycja „14 z 21 dni”),
 *   przełożony, sprzęt, do zrobienia (zadanie wejścia, protokół do podpisu,
 *   timesheet do wysłania);
 * - `?tab=leave` — przerwy Oli (B2B, etap 2 D5: zgłoszenia bez akceptacji):
 *   saldo z umownej puli, zgłoszona przerwa z przekierowaniem poczty i kolizją
 *   od koordynatorki, zgłoszony dzień, anulowane; `&form=uop` — wnioski
 *   urlopowe (zatwierdzony, wpisany, odrzucony z powodem, okolicznościowy
 *   z załącznikiem „akt-slubu.pdf” i „Dołącz kolejny”);
 * - `?state=report` — Ola (B2B) z otwartym oknem „Zgłoś przerwę w świadczeniu
 *   usług” (makieta m5): bez wyboru rodzaju, rozliczenie z puli i „Co się
 *   stanie po zgłoszeniu”;
 * - `?state=request` — Kamil (Delivery Lead, umowa o pracę) z otwartym oknem
 *   „Wniosek o nieobecność”: zastępca proponowany, „Co wypada w tym czasie” (rozmowy
 *   u klienta, prep, screening), nieobecni z działu, saldo po wniosku. Okno
 *   startuje od dziś (tak działa ekran) — podgląd jest zasiany dla „bez
 *   zastępcy” i każdego zastępcy z listy, więc wybór nie wysyła zapytania.
 *   W weekend serwer odpowiada „W wybranym okresie nie ma dni roboczych.” —
 *   harness pokazuje to samo;
 * - `?tab=month` — „Mój miesiąc” Oli: dni do wczoraj wpisane, urlop z wniosku,
 *   nadgodzina, dziś pusty dzień z podpowiedzią opisu („+” przy dniu), jutro
 *   zaplanowane zdalnie; poprzedni miesiąc zaakceptowany (strzałka „‹”);
 * - `?tab=bonuses` — „Premie i stawka”: etapy premii (prognoza, 14 z 21 dni,
 *   przyznane, anulowana przez automat z powodem), „Moje rozliczenie”
 *   (poprzedni miesiąc zamknięty, bieżący szacunek), historia stawki;
 * - `?tab=consents` — „Zgody i wydatki” (22.10.2026, dawne „Ludzie → Moje
 *   zgody”): moduł „Zgody” otwarty, pytanie od zatwierdzającej w „Do zrobienia
 *   przez Ciebie” (licznik 1 na zakładce), szkolenie w toku, zamknięta
 *   subskrypcja. Formularz „Poproś o zgodę” pyta serwer o „Kto zdecyduje” —
 *   w harnessie bez sieci.
 */

import { useState } from "react";

import { LeaveRequestDialog } from "@/components/hr/leave/LeaveRequestDialog";
import { MyTimeScreen } from "@/components/hr/MyTimeScreen";
import { currentYearMonth } from "@/components/hr/time/time-format";
import { equipmentKeys } from "@/lib/api/equipment";
import { approvalKeys } from "@/lib/api/hr-approvals";
import { leaveKeys, type LeaveInput } from "@/lib/api/hr-leave";
import { hrKeys, type EmploymentType } from "@/lib/api/hr";
import { payrollKeys } from "@/lib/api/hr-payroll";
import { timeKeys } from "@/lib/api/hr-time";
import { lifecycleKeys } from "@/lib/api/hr-lifecycle";
import { warsawToday } from "@/lib/warsaw-date";
import { shiftMonth } from "@/lib/date-pl";

import { HR_CAST, harnessMonthDays, hrConfig } from "../hr-fixtures";
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
  OLA_SUBSTITUTES,
  TEMPLATES,
  balance,
  dayHint,
  formBalance,
  kamilPreview,
  kamilRequests,
  myLifecycleTasks,
  myProfile,
  olaConsents,
  olaHistory,
  olaMonth,
  olaPayroll,
  olaReportPreview,
  olaRequests,
  olaSettlement,
} from "./fixtures";

const STATES = ["overview", "leave", "request", "report", "month", "bonuses", "consents"] as const;
type State = (typeof STATES)[number];
const FORMS = ["b2b", "uop", "zlecenie"] as const satisfies readonly EmploymentType[];

const LINKS = [
  { key: "overview", label: "Przegląd (B2B z pulą)", href: "?tab=overview" },
  { key: "overview-uop", label: "Przegląd (UoP)", href: "?tab=overview&form=uop" },
  { key: "overview-zlecenie", label: "Przegląd (zlecenie)", href: "?tab=overview&form=zlecenie" },
  { key: "leave", label: "Przerwy (B2B)", href: "?tab=leave" },
  { key: "leave-uop", label: "Urlopy z załącznikiem (UoP)", href: "?tab=leave&form=uop" },
  { key: "report", label: "Zgłoszenie przerwy (Ola, B2B)", href: "?state=report&tab=leave" },
  { key: "request", label: "Wniosek urlopowy (Kamil, UoP)", href: "?state=request&tab=leave" },
  { key: "month", label: "Raport godzin", href: "?tab=month" },
  { key: "bonuses", label: "Premie i stawka", href: "?tab=bonuses" },
  { key: "consents", label: "Zgody i wydatki", href: "?tab=consents" },
] as const;

function prepare(params: URLSearchParams) {
  const asked = params.get("state");
  const state: State =
    asked === "request" || asked === "report"
      ? asked
      : pickState(params.get("tab"), STATES, "overview");
  // Wniosek z akceptacją jest tylko na umowie o pracę (Kamil); zgłoszenie — B2B (Ola).
  const form: EmploymentType =
    state === "request" ? "uop" : state === "report" ? "b2b" : pickState(params.get("form"), FORMS, "b2b");
  const viewer = state === "request" ? HR_CAST.kamil : HR_CAST.ola;
  const today = warsawToday();
  const current = currentYearMonth();
  const year = current.year;
  const client = harnessQueryClient();
  const base = hrConfig();
  // Moduł „Zgody” jest w harnessach domyślnie wyłączony — otwiera go tylko ten stan.
  const config =
    state === "consents"
      ? { ...base, open_modules: { ...base.open_modules, approvals: true } }
      : base;

  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.me, myProfile(viewer, year, form));
  client.setQueryData(equipmentKeys.me, MY_EQUIPMENT);
  // „Przegląd → Do zrobienia”: moje zadania wejścia/odejścia (klucz `useMyLifecycleTasks`).
  client.setQueryData(lifecycleKeys.myTasks, myLifecycleTasks(today));
  // „Mój przełożony”: Marta w pracy (brak nieobecności).
  client.setQueryData(leaveKeys.absence(String(HR_CAST.marta.id), null), { on: today, items: [] });

  // Urlopy
  if (state === "request") {
    client.setQueryData(leaveKeys.balance(year), { ...balance(year, "9.5", "18.5"), employment_type: "uop" });
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
    client.setQueryData(leaveKeys.balance(year), formBalance(year, today, form));
    client.setQueryData(leaveKeys.mine, olaRequests(current, form));
  }
  if (state === "report") {
    client.setQueryData(leaveKeys.substitutes("self", today, today), OLA_SUBSTITUTES);
    for (const substitute of [null, ...OLA_SUBSTITUTES.map((row) => row.user_id)]) {
      const input: LeaveInput = {
        leave_type: "vacation",
        start_date: today,
        end_date: today,
        half_day: null,
        substitute_user_id: substitute,
      };
      client.setQueryData(leaveKeys.preview("self", input), olaReportPreview(today, substitute));
    }
  }

  // Mój miesiąc: bieżący (szkic), poprzedni (zaakceptowany), następny (pusty) i archiwum.
  client.setQueryData(timeKeys.month(current.year, current.month), olaMonth(current, today, false, form));
  const previous = shiftMonth(current, -1);
  client.setQueryData(timeKeys.month(previous.year, previous.month), olaMonth(previous, today, true, form));
  const next = shiftMonth(current, 1);
  client.setQueryData(timeKeys.month(next.year, next.month), olaMonth(next, today, false, form));
  const history = olaHistory(current);
  client.setQueryData(timeKeys.history, history);
  // Klik miesiąca w archiwum otwiera go w siatce — każdy miesiąc archiwum zasiany.
  for (const item of history.slice(2)) {
    client.setQueryData(timeKeys.month(item.year, item.month), olaMonth(item, today, true, form));
  }
  client.setQueryData(timeKeys.templates, TEMPLATES);
  const monthIso = `${current.year}-${String(current.month).padStart(2, "0")}`;
  for (const day of harnessMonthDays(monthIso)) {
    client.setQueryData(timeKeys.hint(day.date), dayHint(day.date, today));
  }

  // Zgody i wydatki
  if (state === "consents") client.setQueryData(approvalKeys.list("mine"), olaConsents());

  // Premie
  client.setQueryData(payrollKeys.me, olaPayroll(current, today));
  client.setQueryData(payrollKeys.settlement(year), olaSettlement(current));
  // W styczniu „Premie i stawka” pyta też o poprzedni rok — harness bez żądań.
  client.setQueryData(payrollKeys.settlement(year - 1), { year: year - 1, months: [], bonuses_paid: {} });

  return { user: viewer, client, value: { state, config, form } };
}

const FORM_LABELS: Record<EmploymentType, string> = {
  b2b: "B2B z umowną pulą",
  uop: "umowa o pracę",
  zlecenie: "umowa zlecenie",
};

export default function HrMyTimePreviewPage() {
  const ready = useHrHarness(prepare);
  const [dialogOpen, setDialogOpen] = useState(true);
  if (!ready) return <HrHarnessLoading />;
  const { state, config, form } = ready.value;
  const current =
    state === "overview" && form !== "b2b"
      ? `overview-${form}`
      : state === "leave" && form === "uop"
        ? "leave-uop"
        : state;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Mój czas"
      note={
        state === "request"
          ? "Kamil Testowy (Delivery Lead, umowa o pracę) składa wniosek. Dane fikcyjne, bez zapytań."
          : `Ola Przykładowa (rekruterka, ${FORM_LABELS[form]}). Dane fikcyjne, bez zapytań.`
      }
      states={LINKS}
      current={current}
    >
      <MyTimeScreen config={config} />
      {state === "request" || state === "report" ? (
        <LeaveRequestDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          mode="self"
          allowedTypes={["vacation"]}
          employmentType={form}
        />
      ) : null}
    </HrHarnessShell>
  );
}

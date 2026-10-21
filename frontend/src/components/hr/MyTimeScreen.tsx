"use client";

import { type ReactNode } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Card } from "@/components/ui/card";
import {
  useMyHrProfile,
  type EmploymentType,
  type HrConfig,
  type HrModuleKey,
} from "@/lib/api/hr";
import { employmentTerms } from "@/lib/hr-employment-terms";
import { useUrlSyncedState, useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import type { YearMonth } from "@/lib/date-pl";

import { MyLeaveTab } from "./leave/MyLeaveTab";
import { MyOverviewTab } from "./me/MyOverviewTab";
import { MyBonusesTab } from "./payroll/MyBonusesTab";
import { MyMonthTab } from "./time/MyMonthTab";
import { currentYearMonth } from "./time/time-format";
import { MySettlementTab } from "./me/MySettlementTab";

/** Zakładka „Mój czas” zależna od modułu (widoczna, gdy moduł jest otwarty). */
export interface MyTimeModuleTab {
  value: string;
  label: string;
  /** Nazwa zależna od formy współpracy (D4); bez niej — `label`. */
  labelFor?: (form: EmploymentType | null | undefined) => string;
  module: HrModuleKey;
  /** `initialMonth` — miesiąc z adresu (link z powiadomienia o timesheecie). */
  render: (config: HrConfig, initialMonth?: YearMonth) => ReactNode;
}

/**
 * Zakładki modułów „Mój czas”, w kolejności na pasku (po „Przeglądzie”).
 * Zakładka modułu jest widoczna, gdy moduł jest otwarty.
 */
export const MY_TIME_MODULE_TABS: MyTimeModuleTab[] = [
  {
    value: "leave",
    label: "Urlop",
    // „Urlop” (UoP), „Przerwy” (B2B), „Nieobecności” (zlecenie) — etap 2, D4.
    labelFor: (form) => employmentTerms(form).absences_title,
    module: "leave",
    render: () => <MyLeaveTab />,
  },
  {
    value: "month",
    label: "Mój miesiąc",
    // „Ewidencja czasu pracy”, „Raport godzin”, „Potwierdzenie godzin”.
    labelFor: (form) => employmentTerms(form).timesheet,
    module: "time",
    render: (config, initialMonth) => <MyMonthTab config={config} initialMonth={initialMonth} />,
  },
  {
    value: "settlement",
    label: "Rozliczenie",
    module: "settlements",
    render: () => <MySettlementTab />,
  },
  {
    value: "bonuses",
    label: "Premie i stawka",
    // „Wynagrodzenie dodatkowe i stawka” przy B2B i zleceniu (21.10.2026).
    labelFor: (form) => employmentTerms(form).bonuses_tab,
    module: "payroll",
    render: () => <MyBonusesTab />,
  },
];

/** Miesiąc z adresu (`?year=2026&month=10`); zły albo brak = brak. */
export function yearMonthFromParams(params: Pick<URLSearchParams, "get">): YearMonth | undefined {
  const year = Number(params.get("year"));
  const month = Number(params.get("month"));
  if (!Number.isInteger(year) || year < 2020 || year > 2100) return undefined;
  if (!Number.isInteger(month) || month < 1 || month > 12) return undefined;
  return { year, month };
}

const OVERVIEW_TAB = { value: "overview", label: "Przegląd" } as const;

/**
 * Zakładki widoczne dla osoby: „Przegląd” (zawsze pierwszy i domyślny,
 * etap 2 D1) i otwarte moduły. Kartoteka nie ma zakładki — stanowisko,
 * przełożony i link do niej są w karcie „Ja w firmie” na „Przeglądzie”
 * (makieta 21.10.2026; stary `?tab=profile` otwiera „Przegląd”). Nazwy
 * zakładek modułów mówią językiem umowy osoby (`form`; brak = jak umowa o pracę).
 */
export function myTimeTabs(
  config: Pick<HrConfig, "open_modules">,
  tabs: readonly MyTimeModuleTab[] = MY_TIME_MODULE_TABS,
  form?: EmploymentType | null,
): { value: string; label: string }[] {
  return [
    OVERVIEW_TAB,
    ...tabs
      .filter((tab) => config.open_modules[tab.module])
      .map(({ value, label, labelFor }) => ({
        value,
        label: labelFor ? labelFor(form) : label,
      })),
  ];
}

/**
 * „Mój czas” — przegląd, własne nieobecności, miesiąc pracy i premie (moduły
 * włączane etapami). `?tab=` wybiera zakładkę (domyślnie „Przegląd”).
 */
export function MyTimeScreen({ config }: { config: HrConfig }) {
  const me = useMyHrProfile();
  const form = me.data?.has_profile ? me.data.employment_type : null;
  const tabs = myTimeTabs(config, MY_TIME_MODULE_TABS, form);
  const params = useSearchParams();
  // Zakładka z adresu (link z powiadomienia także przy otwartym ekranie), przełączalna ręcznie.
  const [active, setActive] = useUrlSyncedState<string>(params.get("tab"), tabs[0].value);
  const initialMonth = yearMonthFromParams(params);
  const { replaceUrl } = useUrlWriter();
  const current = active && tabs.some((tab) => tab.value === active) ? active : tabs[0].value;
  const state = resolveViewState({
    isLoading: me.isLoading,
    isError: me.isError,
    error: me.error,
    isSuccess: me.isSuccess,
  });

  const moduleTab = MY_TIME_MODULE_TABS.find((tab) => tab.value === current);

  // Przejście z „Przeglądu”: zakładka raportu czyta miesiąc z adresu, więc
  // idzie tam zawsze jawny miesiąc — zaległy z „Do zrobienia” albo bieżący
  // („Uzupełnij dzień”), żeby nie otworzył się ten, który został w adresie.
  const openTab = (value: string, month?: YearMonth) => {
    setActive(value);
    const next = new URLSearchParams(params.toString());
    next.set("tab", value);
    const target = value === "month" ? (month ?? currentYearMonth()) : null;
    if (target) {
      next.set("year", String(target.year));
      next.set("month", String(target.month));
    } else {
      next.delete("year");
      next.delete("month");
    }
    replaceUrl(`?${next.toString()}`);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Mój czas"
        // Przed wczytaniem kartoteki neutralnie (prawie wszyscy są na B2B).
        description={`Nieobecności, miesiąc pracy i ${employmentTerms(form ?? "b2b").bonuses} w jednym miejscu.`}
        density="compact"
      />
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state !== "ready" || !me.data ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => me.refetch()}
        />
      ) : !me.data.has_profile ? (
        <Card className="p-5 text-sm text-muted-foreground">
          Nie masz jeszcze kartoteki w NEXUSIE. Poproś Kadry o jej założenie —
          bez niej nie zgłosisz nieobecności ani nie wyślesz raportu godzin.
        </Card>
      ) : (
        <>
          {tabs.length > 1 ? (
            <div data-help="hr.my_time.tabs">
              <TabbedNav
                ariaLabel="Mój czas"
                overflow="scroll"
                tabs={tabs}
                value={current}
                onValueChange={(value) => openTab(value)}
              />
            </div>
          ) : null}
          {current === OVERVIEW_TAB.value ? (
            <MyOverviewTab config={config} person={me.data} onOpenTab={openTab} />
          ) : moduleTab ? (
            moduleTab.render(config, initialMonth)
          ) : null}
        </>
      )}
    </div>
  );
}

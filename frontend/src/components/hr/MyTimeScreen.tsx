"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/ds/PageHeader";
import { PersonEquipmentPanel } from "@/components/equipment/PersonEquipmentPanel";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Card } from "@/components/ui/card";
import { useMyHrProfile, type HrConfig, type HrModuleKey, type PersonFull } from "@/lib/api/hr";
import { useUrlSyncedState } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";

import { MyLeaveTab } from "./leave/MyLeaveTab";
import { formatDays } from "./people/hr-format";
import { MyBonusesTab } from "./payroll/MyBonusesTab";
import { MyMonthTab } from "./time/MyMonthTab";
import type { YearMonth } from "./time/time-format";

function warsawYear(): number {
  return Number(
    new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw", year: "numeric" }).format(
      new Date(),
    ),
  );
}

/** Zakładka „Mój czas” zależna od modułu (widoczna, gdy moduł jest otwarty). */
export interface MyTimeModuleTab {
  value: string;
  label: string;
  module: HrModuleKey;
  /** `initialMonth` — miesiąc z adresu (link z powiadomienia o timesheecie). */
  render: (config: HrConfig, initialMonth?: YearMonth) => ReactNode;
}

/**
 * Zakładki modułów „Mój czas”, w kolejności na pasku. Punkt rozszerzenia:
 * „Mój miesiąc” (moduł `time`) i „Premie” (moduł `payroll`) dopisują tu swoje
 * wpisy razem z komponentami — do tego czasu ich zakładek nie ma wcale.
 */
export const MY_TIME_MODULE_TABS: MyTimeModuleTab[] = [
  { value: "leave", label: "Urlopy", module: "leave", render: () => <MyLeaveTab /> },
  {
    value: "month",
    label: "Mój miesiąc",
    module: "time",
    render: (config, initialMonth) => <MyMonthTab config={config} initialMonth={initialMonth} />,
  },
  { value: "bonuses", label: "Premie", module: "payroll", render: () => <MyBonusesTab /> },
];

/** Miesiąc z adresu (`?year=2026&month=10`); zły albo brak = brak. */
export function yearMonthFromParams(params: Pick<URLSearchParams, "get">): YearMonth | undefined {
  const year = Number(params.get("year"));
  const month = Number(params.get("month"));
  if (!Number.isInteger(year) || year < 2020 || year > 2100) return undefined;
  if (!Number.isInteger(month) || month < 1 || month > 12) return undefined;
  return { year, month };
}

const PROFILE_TAB = { value: "profile", label: "Kartoteka" } as const;

/** Zakładki widoczne dla osoby: otwarte moduły + kartoteka (zawsze na końcu). */
export function myTimeTabs(
  config: Pick<HrConfig, "open_modules">,
  tabs: readonly MyTimeModuleTab[] = MY_TIME_MODULE_TABS,
): { value: string; label: string }[] {
  return [
    ...tabs
      .filter((tab) => config.open_modules[tab.module])
      .map(({ value, label }) => ({ value, label })),
    PROFILE_TAB,
  ];
}

function ProfileCard({ person, leaveOpen }: { person: PersonFull; leaveOpen: boolean }) {
  const year = warsawYear();
  const pool = person.entitlements?.find((row) => row.year === year);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card className="space-y-1 p-5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Moja kartoteka
        </h2>
        <p className="text-sm text-foreground">
          {[person.job_title, person.department].filter(Boolean).join(" · ") ||
            "Stanowisko nieuzupełnione"}
        </p>
        {person.manager_name ? (
          <p className="text-sm text-muted-foreground">Przełożony: {person.manager_name}</p>
        ) : null}
        <Link href={`/people/${person.user_id}`} className="text-sm text-primary hover:underline">
          Otwórz kartotekę
        </Link>
      </Card>
      <Card className="space-y-1 p-5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Pula urlopowa {year}
        </h2>
        {!pool ? (
          <p className="text-sm text-muted-foreground">
            Pula na {year} nie jest ustawiona — zrobią to Kadry.
          </p>
        ) : (
          <p className="text-sm text-foreground">
            Pula:{" "}
            <strong>
              {pool.entitlement_days == null
                ? "bez puli"
                : `${formatDays(pool.entitlement_days)} dni`}
            </strong>
            {Number(pool.carried_over_days) > 0
              ? ` + ${formatDays(pool.carried_over_days)} dni zaległego`
              : ""}
          </p>
        )}
        {!leaveOpen ? (
          <p className="text-xs text-muted-foreground">
            Wnioski urlopowe ruszą po włączeniu modułu urlopów.
          </p>
        ) : null}
      </Card>
    </div>
  );
}

/** „Mój czas” — własne urlopy, miesiąc pracy i premie (moduły włączane etapami). */
export function MyTimeScreen({ config }: { config: HrConfig }) {
  const me = useMyHrProfile();
  const tabs = myTimeTabs(config);
  const params = useSearchParams();
  // Zakładka z adresu (link z powiadomienia także przy otwartym ekranie), przełączalna ręcznie.
  const [active, setActive] = useUrlSyncedState<string>(params.get("tab"), tabs[0].value);
  const initialMonth = yearMonthFromParams(params);
  const current = active && tabs.some((tab) => tab.value === active) ? active : tabs[0].value;
  const state = resolveViewState({
    isLoading: me.isLoading,
    isError: me.isError,
    error: me.error,
    isSuccess: me.isSuccess,
  });

  const moduleTab = MY_TIME_MODULE_TABS.find((tab) => tab.value === current);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Mój czas"
        description="Urlopy, miesiąc pracy i premie w jednym miejscu."
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
          Nie masz jeszcze kartoteki pracownika. Poproś Kadry o jej założenie —
          bez niej nie złożysz wniosku urlopowego ani nie wyślesz timesheetu.
        </Card>
      ) : (
        <>
          {tabs.length > 1 ? (
            <TabbedNav
              ariaLabel="Mój czas"
              overflow="scroll"
              tabs={tabs}
              value={current}
              onValueChange={setActive}
            />
          ) : null}
          {moduleTab ? (
            moduleTab.render(config, initialMonth)
          ) : (
            <div className="space-y-4">
              <ProfileCard person={me.data} leaveOpen={config.open_modules.leave} />
              {/* Mój sprzęt (moduł „Sprzęt”) — pusty stan = brak wydanych rzeczy. */}
              {config.open_modules.equipment ? <PersonEquipmentPanel userId="mine" /> : null}
            </div>
          )}
        </>
      )}
    </div>
  );
}

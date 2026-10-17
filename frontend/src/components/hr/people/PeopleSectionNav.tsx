"use client";

import { useRouter } from "next/navigation";

import { TabbedNav } from "@/components/ds/TabbedNav";
import { useHrCounts, type HrConfig, type HrCounts } from "@/lib/api/hr";

export type PeopleSection =
  | "directory"
  | "calendar"
  | "approvals"
  | "cases"
  | "payroll";

interface PeopleSectionLink {
  value: PeopleSection;
  label: string;
  href: string;
}

/**
 * Zakładki obszaru „Ludzie” widoczne dla tej osoby. Serwer i tak broni każdej
 * trasy; tu decydujemy tylko, czego nie pokazywać na pasku.
 *
 * * Katalog — moduł „Ludzie”,
 * * Kalendarz zespołu — moduł urlopów i kartoteka (albo Kadry),
 * * Akceptacje — przełożony (ma podwładnych) albo Kadry, gdy działa urlop lub czas,
 * * Sprawy — uprawnienie „Sprawy” albo przypisana sprawa,
 * * Płace — uprawnienie „Płace”.
 */
export function peopleSections(config: HrConfig): PeopleSectionLink[] {
  const { me, open_modules: open } = config;
  const staff = me.has_profile || me.people_admin || me.is_admin;
  const approver =
    me.is_manager || (me.covering?.length ?? 0) > 0 || me.people_admin || me.is_admin;
  const links: PeopleSectionLink[] = [];
  if (open.people) links.push({ value: "directory", label: "Katalog", href: "/people" });
  if (open.leave && staff) {
    links.push({ value: "calendar", label: "Kalendarz zespołu", href: "/people/calendar" });
  }
  if ((open.leave || open.time) && approver) {
    links.push({ value: "approvals", label: "Akceptacje", href: "/people/approvals" });
  }
  if (open.cases && (me.cases || me.is_admin || me.has_assigned_cases)) {
    links.push({ value: "cases", label: "Sprawy", href: "/people/cases" });
  }
  if (open.payroll && (me.payroll || me.is_admin)) {
    links.push({ value: "payroll", label: "Płace", href: "/people/payroll" });
  }
  return links;
}

/**
 * Liczba przy zakładce: „Akceptacje” — wnioski i timesheety czekające na
 * decyzję osoby, „Sprawy” — jej otwarte sprawy. Tylko z udanego odczytu:
 * awaria i „nie dotyczy” (`null`) to brak liczby, nigdy „0”.
 */
export function sectionCount(
  section: PeopleSection,
  counts: HrCounts | undefined,
): number | undefined {
  const value =
    section === "approvals" ? counts?.approvals : section === "cases" ? counts?.cases : null;
  return typeof value === "number" ? value : undefined;
}

/** Pasek zakładek obszaru „Ludzie” — wspólny dla katalogu i podstron modułów. */
export function PeopleSectionNav({
  config,
  active,
}: {
  config: HrConfig;
  active: PeopleSection;
}) {
  const router = useRouter();
  const links = peopleSections(config);
  const counted =
    links.length > 1 && links.some(({ value }) => value === "approvals" || value === "cases");
  const counts = useHrCounts(counted);
  // Po awarii odświeżenia `data` zostaje z poprzedniego odczytu — liczba tylko
  // przy udanym odczycie, żeby stara wartość nie udawała aktualnej.
  const current = counts.isSuccess ? counts.data : undefined;
  if (links.length < 2) return null;
  return (
    <TabbedNav
      ariaLabel="Ludzie"
      overflow="scroll"
      tabs={links.map(({ value, label }) => ({
        value,
        label,
        count: sectionCount(value, current),
      }))}
      value={active}
      onValueChange={(value) => {
        const target = links.find((link) => link.value === value);
        if (target) router.push(target.href);
      }}
    />
  );
}

"use client";

import { useRouter } from "next/navigation";

import { TabbedNav } from "@/components/ds/TabbedNav";
import { useHrCounts, type HrConfig, type HrCounts } from "@/lib/api/hr";

export type PeopleSection =
  | "directory"
  | "team"
  | "calendar"
  | "approvals"
  | "payroll";

interface PeopleSectionLink {
  value: PeopleSection;
  label: string;
  href: string;
}

/**
 * Zakładki obszaru „Ludzie” widoczne dla tej osoby (przebudowa 22.10.2026):
 * zawsze w tej samej kolejności Katalog · Mój zespół · Kalendarz · Akceptacje
 * · Płace — kto nie ma dostępu, nie widzi zakładki, reszta się nie przestawia.
 * Serwer i tak broni każdej trasy; tu decydujemy tylko, czego nie pokazywać.
 *
 * * Katalog — moduł „Ludzie”; Kadry i admin mają w nim widok „Schemat”
 *   (dawna zakładka „Struktura”, `/people/structure` przekierowuje),
 * * Mój zespół — moduł „Ludzie” i podwładni z kartoteką (Kadry i admin
 *   oglądają cudze zespoły ze Schematu, `?manager=`),
 * * Kalendarz — moduł urlopów i kartoteka (albo Kadry),
 * * Akceptacje — przełożony (ma podwładnych) albo Kadry, gdy działa urlop lub czas;
 *   przy module „Zgody” także przełożony i admin (zatwierdzający),
 * * Płace — uprawnienie „Płace”.
 *
 * „Sprawy” administracja@ są od 22.10.2026 w „Opiece” → „Do zrobienia”
 * (`/people/cases` przekierowuje).
 * „Moje zgody” (własne prośby) są w „Moim czasie” → „Zgody i wydatki”.
 */
export function peopleSections(config: HrConfig): PeopleSectionLink[] {
  const { me, open_modules: open } = config;
  const staff = me.has_profile || me.people_admin || me.is_admin;
  const approver =
    me.is_manager ||
    (me.covering?.length ?? 0) > 0 ||
    me.people_admin ||
    me.timesheets === true ||
    me.is_admin;
  const links: PeopleSectionLink[] = [];
  if (open.people) links.push({ value: "directory", label: "Katalog", href: "/people" });
  if (open.people && me.is_manager) {
    links.push({ value: "team", label: "Mój zespół", href: "/people/team" });
  }
  if (open.leave && staff) {
    links.push({ value: "calendar", label: "Kalendarz", href: "/people/calendar" });
  }
  if (((open.leave || open.time) && approver) || (open.approvals && (me.is_manager || me.is_admin))) {
    links.push({ value: "approvals", label: "Akceptacje", href: "/people/approvals" });
  }
  if (open.payroll && (me.payroll || me.is_admin)) {
    links.push({ value: "payroll", label: "Płace", href: "/people/payroll" });
  }
  return links;
}

/**
 * Liczba przy zakładce „Akceptacje” — wnioski, timesheety i zgody czekające na
 * decyzję osoby. Tylko z udanego odczytu:
 * awaria i „nie dotyczy” (`null`) to brak liczby, nigdy „0”.
 */
export function sectionCount(
  section: PeopleSection,
  counts: HrCounts | undefined,
): number | undefined {
  if (section === "approvals") {
    // Wnioski, timesheety i zgody — jedna liczba spraw czekających na decyzję.
    const parts = [counts?.approvals, counts?.consents].filter(
      (part): part is number => typeof part === "number",
    );
    return parts.length > 0 ? parts.reduce((sum, part) => sum + part, 0) : undefined;
  }
  return undefined;
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
    links.length > 1 && links.some(({ value }) => value === "approvals");
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

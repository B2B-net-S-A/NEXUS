"use client";

import { useMemo } from "react";
import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";

import { visibleNavEntries } from "@/lib/nav-registry";
import { useAuthStore } from "@/store/auth";

export interface HelpGeneratorLink {
  label: string;
  where: string;
  href: string;
  /** Pozycja menu, której bramkę dzieli odnośnik — nie prowadzimy tam, dokąd nie prowadzi menu. */
  navId: string;
}

/**
 * Dawne wzory Word z Pomocy → miejsca, w których te dokumenty powstają
 * w NEXUSIE (decyzja Artura 26.11.2026, wariant B z makiet).
 */
export const HELP_GENERATOR_LINKS: readonly HelpGeneratorLink[] = [
  {
    label: "Umowa B2B",
    where: "Generator Umów B2B",
    href: "/contracts/b2b-generator",
    navId: "b2b-generator",
  },
  {
    label: "Umowa przedwstępna",
    where: "Rekrutacje → Umowy przedwstępne",
    href: "/jobs/umowy-przedwstepne",
    navId: "pre-contracts",
  },
  {
    label: "Profil Championa",
    where: "Rekrutacja → Profil Championa",
    href: "/jobs",
    navId: "jobs",
  },
  {
    label: "Notatka po screeningu",
    where: "Tablica → karta osoby → Screening",
    href: "/jobs",
    navId: "jobs",
  },
  {
    label: "Zaproszenie na prep",
    where: "Rekrutacja → Rozmowy → Zaproś na prep",
    href: "/jobs",
    navId: "jobs",
  },
];

/**
 * Pasek nad zakładkami Pomocy: „wzorów w Wordzie już tu nie ma”. Rekruterzy
 * pobierali z Materiałów wzory umowy, Profilu Championa i notatki zamiast
 * robić je w NEXUSIE; pasek mówi, gdzie są teraz. Bez żadnego odnośnika
 * (np. rola bez Rekrutacji) pasek się nie pokazuje.
 */
export function HelpGeneratorsNotice() {
  const user = useAuthStore((state) => state.user);
  const links = useMemo(() => {
    const visible = new Set(
      visibleNavEntries(user, { contactQueueEnabled: false }).map((entry) => entry.id),
    );
    return HELP_GENERATOR_LINKS.filter((link) => visible.has(link.navId));
  }, [user]);

  if (links.length === 0) return null;

  return (
    <section
      aria-label="Dokumenty robisz w NEXUSIE"
      className="rounded-lg border border-primary/30 bg-primary/5 p-4"
    >
      <p className="text-sm font-semibold text-foreground flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
        Wzorów w Wordzie już tu nie ma — te dokumenty robisz w NEXUSIE
      </p>
      <p className="text-xs text-muted-foreground mt-1">
        Generator bierze dane z rekrutacji i osoby, więc nie przepisujesz ich ręcznie, a
        dokument zostaje w historii.
      </p>
      <ul className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
        {links.map((link) => (
          <li key={link.label}>
            <Link
              href={link.href}
              className="block h-full rounded-md border border-border bg-card px-3 py-2 hover:bg-primary/10 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex items-center justify-between gap-2 text-sm font-medium text-foreground">
                {link.label}
                <ArrowRight className="h-3.5 w-3.5 text-primary shrink-0" aria-hidden="true" />
              </span>
              <span className="block text-xs text-muted-foreground mt-0.5">{link.where}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

"use client";

import { useMemo, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { StructureTodoSection } from "@/components/hr/structure/StructureTodo";
import { todoItems } from "@/components/hr/structure/structure-tree";
import { apiErrorMessage } from "@/lib/api-error";
import { useAccountMismatches, usePeople, type HrConfig } from "@/lib/api/hr";
import { useHrStructure } from "@/lib/api/hr-structure";

import { AccountMismatchesSection, accountTodoCount } from "./AccountMismatchesPanel";
import {
  canSeeAccounts,
  canSeeStructure,
  pendingPeople,
  tidyPart,
  tidyTotal,
  type TidyPart,
} from "./tidy-up";

/**
 * „Porządki · N” (22.10.2026): jeden przycisk w nagłówku „Ludzi” zamiast
 * żółtego paska „Do wyrównania” i panelu „Do uporządkowania” Struktury.
 * Panel z prawej ma dwie sekcje, każda za swoją bramką: „Struktura” (Kadry
 * i admin) i „Konta i kartoteki” (admin, Finanse, Kadry). N = suma obu;
 * awaria odczytu = przycisk bez liczby (nigdy „0”); nic do zrobienia = bez
 * przycisku.
 */
export function PeopleTidyUp({ config }: { config: HrConfig }) {
  const seesStructure = canSeeStructure(config);
  const seesAccounts = canSeeAccounts(config);
  const people = usePeople();
  const structure = useHrStructure(seesStructure);
  const mismatches = useAccountMismatches(seesAccounts);
  const [open, setOpen] = useState(false);

  const pending = useMemo(() => pendingPeople(people.data?.items ?? []), [people.data]);
  const structurePart = tidyPart(seesStructure, structure, (data) => todoItems(data).length);
  // Kartoteki „do uzupełnienia” liczą się z katalogu — bez niego liczba byłaby zgadywana.
  const accountsPart: TidyPart = people.isError
    ? seesAccounts
      ? { status: "error" }
      : { status: "off" }
    : people.data === undefined && seesAccounts
      ? { status: "loading" }
      : tidyPart(seesAccounts, mismatches, (data) => accountTodoCount(data, pending));
  const total = tidyTotal([structurePart, accountsPart]);
  if (total.kind === "hidden" && !open) return null;

  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        title={total.kind === "unknown" ? "Nie udało się policzyć wszystkich pozycji" : undefined}
      >
        {total.kind === "unknown" ? (
          <AlertTriangle className="h-4 w-4 text-warning-muted-foreground" aria-hidden />
        ) : null}
        {total.kind === "count" ? `Porządki · ${total.count}` : "Porządki"}
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" size="lg">
          <SheetHeader>
            <SheetTitle>Porządki</SheetTitle>
            <SheetDescription>
              Struktura i kartoteki do uporządkowania. Każda zmiana działa od razu.
            </SheetDescription>
          </SheetHeader>
          <SheetBody className="space-y-6">
            {seesStructure ? (
              <TidySection title="Struktura" part={structurePart}>
                {structure.isError ? (
                  <ReadError
                    message={apiErrorMessage(structure.error, "Nie udało się wczytać struktury.")}
                    onRetry={() => structure.refetch()}
                  />
                ) : structure.data ? (
                  <StructureTodoSection data={structure.data} />
                ) : (
                  <Loading />
                )}
              </TidySection>
            ) : null}
            {seesAccounts ? (
              <TidySection title="Konta i kartoteki" part={accountsPart}>
                {mismatches.isError || people.isError ? (
                  <ReadError
                    message={apiErrorMessage(
                      mismatches.error ?? people.error,
                      "Nie udało się sprawdzić kartotek z kontami.",
                    )}
                    onRetry={() => {
                      if (mismatches.isError) mismatches.refetch();
                      if (people.isError) people.refetch();
                    }}
                  />
                ) : mismatches.data && people.data ? (
                  <AccountMismatchesSection data={mismatches.data} pendingPeople={pending} />
                ) : (
                  <Loading />
                )}
              </TidySection>
            ) : null}
          </SheetBody>
        </SheetContent>
      </Sheet>
    </>
  );
}

function TidySection({
  title,
  part,
  children,
}: {
  title: string;
  part: TidyPart;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="space-y-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
        {title}
        {part.status === "ok" ? (
          <span
            className={
              part.count > 0
                ? "rounded-full bg-warning-muted px-2 py-0.5 text-[11px] font-semibold text-warning-muted-foreground"
                : "rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground"
            }
          >
            {part.count}
          </span>
        ) : null}
      </h3>
      {children}
    </section>
  );
}

function ReadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-destructive">
      {message}
      <Button size="sm" variant="outline" onClick={onRetry}>
        Spróbuj ponownie
      </Button>
    </div>
  );
}

function Loading() {
  return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
}

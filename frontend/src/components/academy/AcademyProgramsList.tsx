"use client";

/**
 * Akademia — lista programów (np. „Akademia Rekrutera”) z licznikami etapów.
 * Nowy program zakłada admin albo Head of Recruitment.
 */

import * as React from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/ds/EmptyState";
import { PageHeader } from "@/components/ds/PageHeader";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { academyApi, academyKeys, type AcademyProgramListItem } from "@/lib/api/academy";

export function AcademyProgramsList() {
  const programs = useQuery({ queryKey: academyKeys.programs(), queryFn: academyApi.programs });
  const router = useRouter();
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [name, setName] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const nameId = React.useId();

  const create = async () => {
    setCreating(true);
    try {
      const program = await academyApi.createProgram({
        name: name.trim(),
        conditions: ["Umowa zlecenie — pasuje?", "Praca stacjonarna w biurze — pasuje?"],
      });
      await queryClient.invalidateQueries({ queryKey: academyKeys.programs() });
      router.push(`/academy/${program.id}?view=settings`);
    } catch (err) {
      showError(apiErrorMessage(err, "Nie udało się założyć akademii."));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Akademia"
        description="Nabór do programów szkoleniowych: ogłoszenia → telefon → spotkanie w biurze → zadanie → umowa."
      />
      {programs.isError ? (
        <EmptyState
          title="Nie udało się wczytać akademii"
          description={apiErrorMessage(programs.error, "Spróbuj odświeżyć stronę.")}
        />
      ) : !programs.isSuccess ? (
        <p className="text-sm text-muted-foreground">Wczytuję…</p>
      ) : (
        <>
          {programs.data.items.length === 0 ? (
            <EmptyState
              title="Nie ma jeszcze żadnej akademii"
              description={
                programs.data.can_manage
                  ? "Załóż program poniżej, a potem podepnij ogłoszenia, z których mają przychodzić ludzie."
                  : "Program zakłada admin albo Head of Recruitment."
              }
            />
          ) : (
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {programs.data.items.map((p) => (
                <ProgramCard key={p.id} program={p} />
              ))}
            </ul>
          )}
          {programs.data.can_manage ? (
            <section className="max-w-xl space-y-3 rounded-xl border border-dashed border-border bg-card p-5">
              <h2 className="text-sm font-semibold">Nowa akademia</h2>
              <label htmlFor={nameId} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Nazwa programu
                <input
                  id={nameId}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="np. Akademia Rekrutera"
                  className="rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground"
                />
              </label>
              <Button disabled={creating || name.trim().length < 2} onClick={() => void create()}>
                Załóż i przejdź do ustawień
              </Button>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}

function ProgramCard({ program }: { program: AcademyProgramListItem }) {
  const c = program.counts;
  const inProgress =
    (c.to_call ?? 0) + (c.scheduled ?? 0) + (c.task_given ?? 0) + (c.task_passed ?? 0) + (c.contract_sent ?? 0);
  return (
    <li>
      <Link
        href={`/academy/${program.id}`}
        className="flex h-full flex-col gap-3 rounded-xl border border-border bg-card p-5 hover:border-primary/40"
      >
        <div className="flex items-center gap-2">
          <h2 className="min-w-0 flex-1 truncate text-base font-semibold">{program.name}</h2>
          <Badge variant={program.is_active ? "success" : "outline"}>
            {program.is_active ? "nabór aktywny" : "wstrzymany"}
          </Badge>
        </div>
        <dl className="grid grid-cols-3 gap-2 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">Do telefonu</dt>
            <dd className="text-lg font-semibold tabular-nums">{c.to_call ?? 0}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">W procesie</dt>
            <dd className="text-lg font-semibold tabular-nums">{inProgress}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Podpisali</dt>
            <dd className="text-lg font-semibold tabular-nums">{c.signed ?? 0}</dd>
          </div>
        </dl>
        <p className="text-xs text-muted-foreground">
          {program.sources_count} ogłosz. · {c.rejected ?? 0} wykluczonych
          {c.luna_skipped ? ` · ${c.luna_skipped} czeka na zatwierdzenie` : ""}
        </p>
      </Link>
    </li>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ellipsis, FileText, Plus, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { resolveViewState } from "@/lib/view-state";
import {
  FAMILY_LABELS,
  RHYTHM_LABELS,
  getClientCatalog,
  setDefinitionStatus,
  shortDate,
  suggestFromContracts,
  type ReportDefinition,
  type ReportFamily,
  type SuggestResult,
} from "@/lib/api/client-reports";
import { DefinitionFormDialog } from "./DefinitionFormDialog";
import { ReportDownloadDialog } from "./ReportDownloadDialog";
import { ReportStateDot } from "./ReportStateDot";

const FAMILIES: ReportFamily[] = ["settlement", "management", "compliance", "on_request"];

function sourceText(definition: ReportDefinition): string {
  if (definition.source_kind === "dl") return definition.source_ref || "od Delivery Leada";
  if (definition.source_kind === "manual") return definition.source_ref || "wpis ręczny";
  const where = definition.source_kind === "amendment" ? "aneks" : "umowa";
  return definition.source_ref ? `${where}, ${definition.source_ref}` : where;
}

/** Zakładka „Raporty” w karcie klienta: co klient wymaga i jedno okno pobrania. */
export function ClientReportsTab({ clientId }: { clientId: number }) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [open, setOpen] = useState<ReportDefinition | null>(null);
  const [editing, setEditing] = useState<ReportDefinition | null>(null);
  const [adding, setAdding] = useState(false);
  const [found, setFound] = useState<SuggestResult | null>(null);

  const query = useQuery({ queryKey: ["client-reports", clientId], queryFn: () => getClientCatalog(clientId) });
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: false,
    isSuccess: query.isSuccess,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["client-reports", clientId] });
    void queryClient.invalidateQueries({ queryKey: ["client-reports-calendar"] });
  };

  const status = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "confirm" | "reject" | "archive" }) => setDefinitionStatus(id, action),
    onSuccess: (saved) => {
      showSuccess(
        saved.status === "active" ? "Raport obowiązuje." : saved.status === "rejected" ? "Propozycja odrzucona." : "Raport zarchiwizowany.",
      );
      refresh();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić raportu.")),
  });
  const suggest = useMutation({
    mutationFn: () => suggestFromContracts(clientId),
    onSuccess: (result) => {
      setFound(result);
      refresh();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się przeszukać umów.")),
  });

  if (viewState === "loading") {
    return <div className="p-6 text-sm text-muted-foreground">Wczytuję raporty klienta…</div>;
  }
  if (viewState === "forbidden" || viewState === "not_found" || viewState === "error") {
    return (
      <div className="p-6">
        <QueryStateNotice state={viewState} onRetry={() => void query.refetch()} />
      </div>
    );
  }
  const data = query.data;
  const rows = data?.definitions ?? [];
  const canEdit = Boolean(data?.can_edit);
  const proposals = rows.filter((d) => d.status === "proposal").length;
  const overdue = rows.filter((d) => d.status === "active" && d.next.state === "overdue").length;

  const archive = async (definition: ReportDefinition) => {
    const ok = await askConfirm({
      title: `Zarchiwizować „${definition.name}”?`,
      description: "Raport zniknie z katalogu i kalendarza. Historia wysyłek zostaje.",
      confirmLabel: "Archiwizuj",
      variant: "destructive",
    });
    if (ok) status.mutate({ id: definition.id, action: "archive" });
  };

  return (
    <div className="space-y-3 p-3 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="font-display text-base font-semibold text-foreground">Raporty dla klienta</h2>
          <p className="text-xs text-muted-foreground">
            Co klient wymaga, z jakiego zapisu umowy albo od kogo, kto przygotowuje i kiedy.
          </p>
        </div>
        <InlineStats
          stats={[
            { id: "all", label: "raportów w katalogu", value: rows.length },
            { id: "over", label: "po terminie", value: overdue },
            { id: "prop", label: "propozycje do zatwierdzenia", value: proposals },
          ]}
        />
        {canEdit ? (
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" onClick={() => suggest.mutate()} loading={suggest.isPending}>
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" /> Znajdź w umowach
            </Button>
            <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
              <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj raport
            </Button>
          </div>
        ) : null}
      </div>

      {found ? <SuggestSummary result={found} clientId={clientId} onClose={() => setFound(null)} /> : null}

      {query.isSuccess && rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Katalog jest pusty. „Znajdź w umowach” zaproponuje raporty z umowy ramowej i aneksów, „Dodaj raport” wpisze raport ustalony z klientem.
        </p>
      ) : null}

      {rows.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[880px] table-fixed text-sm">
            <colgroup>
              <col className="w-[27%]" />
              <col className="w-[17%]" />
              <col className="w-[15%]" />
              <col className="w-[18%]" />
              <col className="w-[12%]" />
              <col className="w-[11%]" />
            </colgroup>
            <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Raport</th>
                <th className="px-3 py-2 font-medium">Źródło wymogu</th>
                <th className="px-3 py-2 font-medium">Rytm i termin</th>
                <th className="px-3 py-2 font-medium">Komu · kto przygotowuje</th>
                <th className="px-3 py-2 font-medium">Następny</th>
                <th className="px-3 py-2">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            {FAMILIES.map((family) => {
              const group = rows.filter((d) => d.family === family);
              if (group.length === 0) return null;
              return (
                <tbody key={family} className="divide-y divide-border">
                  <tr className="bg-muted/20">
                    <td colSpan={6} className="px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                      {FAMILY_LABELS[family]}
                    </td>
                  </tr>
                  {group.map((d) => (
                    <tr key={d.id} className="h-12 align-middle">
                      <td className="px-3 py-1.5">
                        <div className="font-medium leading-5 text-foreground">{d.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {[d.file_format, d.channel, d.generator_key ? "NEXUS liczy" : "plik spoza NEXUSA"].filter(Boolean).join(" · ")}
                        </div>
                      </td>
                      <td className="px-3 py-1.5 text-xs">
                        {d.source_contract_id ? (
                          <Link href={`/clients/${clientId}?tab=umowy-ramowe`} className="text-primary underline-offset-2 hover:underline">
                            {sourceText(d)}
                          </Link>
                        ) : (
                          <span className="text-foreground">{sourceText(d)}</span>
                        )}
                        {d.status === "proposal" ? <div className="text-warning">propozycja — do zatwierdzenia</div> : null}
                      </td>
                      <td className="px-3 py-1.5 text-xs">
                        <div className="text-foreground">{RHYTHM_LABELS[d.rhythm]}</div>
                        <div className="text-muted-foreground">{d.due_label}</div>
                      </td>
                      <td className="px-3 py-1.5 text-xs">
                        <div className="text-foreground">{d.recipient || "—"}</div>
                        <div className="text-muted-foreground">{d.preparer_label}</div>
                      </td>
                      <td className="px-3 py-1.5 text-xs">
                        {d.status === "active" && d.next.state ? (
                          <ReportStateDot
                            state={d.next.state}
                            note={[d.next.due ? shortDate(d.next.due) : null, d.next.period_label].filter(Boolean).join(" · ")}
                          />
                        ) : (
                          <span className="text-muted-foreground">{d.status === "proposal" ? "—" : "zdarzeniowo"}</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex items-center justify-end gap-1">
                          {d.status === "proposal" && d.can_confirm ? (
                            <Button size="sm" variant="outline" onClick={() => status.mutate({ id: d.id, action: "confirm" })}>
                              Zatwierdź
                            </Button>
                          ) : d.family === "settlement" && !d.generator_key ? (
                            <Button size="sm" variant="ghost" asChild>
                              <Link href={`/finance?view=settlements&stClient=${clientId}`}>Rozliczenia →</Link>
                            </Button>
                          ) : d.status === "active" ? (
                            <Button size="sm" variant="outline" onClick={() => setOpen(d)}>
                              <FileText className="h-3.5 w-3.5" aria-hidden="true" /> {d.generator_key ? "Pobierz" : "Wysyłka"}
                            </Button>
                          ) : null}
                          {canEdit ? (
                            <DropdownMenu modal={false}>
                              <DropdownMenuTrigger asChild>
                                <button
                                  type="button"
                                  aria-label={`Więcej: ${d.name}`}
                                  className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                                >
                                  <Ellipsis className="h-4 w-4" />
                                </button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onSelect={() => setOpen(d)}>Historia i pobranie</DropdownMenuItem>
                                <DropdownMenuItem onSelect={() => setEditing(d)}>Zmień</DropdownMenuItem>
                                {d.status === "proposal" && d.can_confirm ? (
                                  <DropdownMenuItem onSelect={() => status.mutate({ id: d.id, action: "reject" })}>Odrzuć propozycję</DropdownMenuItem>
                                ) : null}
                                {d.status === "active" && d.can_confirm ? (
                                  <DropdownMenuItem onSelect={() => void archive(d)}>Archiwizuj</DropdownMenuItem>
                                ) : null}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              );
            })}
          </table>
        </div>
      ) : null}

      <ReportDownloadDialog definition={open} canEdit={canEdit} onClose={() => setOpen(null)} />
      {adding || editing ? (
        <DefinitionFormDialog
          clientId={clientId}
          definition={editing}
          open
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
        />
      ) : null}
      {confirmDialog}
    </div>
  );
}

function SuggestSummary({ result, clientId, onClose }: { result: SuggestResult; clientId: number; onClose: () => void }) {
  const created = result.created.length;
  return (
    <section className="space-y-2 rounded-lg border border-border bg-muted/20 p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="text-foreground">
          {result.message
            ? result.message
            : created
              ? `Dodano ${created} propozycj${created === 1 ? "ę" : created < 5 ? "e" : "i"} z umów — sprawdź je i zatwierdź.`
              : result.model_used
                ? "Nie znalazłem nowych raportów poza tymi, które są już w katalogu."
                : "Odczyt umów przez AI jest niedostępny. Poniżej fragmenty ze słowami o raportach — dodaj raport ręcznie."}
        </p>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Zamknij
        </Button>
      </div>
      {result.fragments.length > 0 ? (
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Fragmenty umów bez propozycji ({result.fragments.length})
          </summary>
          <ul className="mt-2 space-y-1.5">
            {result.fragments.map((fragment) => (
              <li key={fragment.chunk_id} className="text-xs">
                <Link href={`/clients/${clientId}?tab=umowy-ramowe`} className="text-primary hover:underline">
                  {fragment.document}
                </Link>{" "}
                <span className="text-muted-foreground">{fragment.snippet}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

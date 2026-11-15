"use client";

import { useMemo, useState } from "react";
import { Download, Plus } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useRunTemplates,
  useTemplates,
  type InvoiceTemplate,
  type TemplateKind,
} from "@/lib/api/issued-invoices";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

import { splitPeriod } from "../invoicing-format";
import { ImportTemplatesDialog } from "./ImportTemplatesDialog";
import { TemplateDialog } from "./TemplateDialog";

const FILTERS: { value: TemplateKind | null; label: string }[] = [
  { value: null, label: "Wszystkie" },
  { value: "service", label: "Usługi" },
  { value: "benefit", label: "Refaktury benefitów" },
];

function TemplateState({ template }: { template: InvoiceTemplate }) {
  if (template.issued) {
    return (
      <a
        href={`/finance/faktury/${template.issued.id}`}
        className="block truncate text-sm text-primary hover:underline"
      >
        {template.issued.invoice_number
          ? `${template.issued.invoice_number} · ${template.issued.status_label}`
          : template.issued.status_label}
      </a>
    );
  }
  if (!template.active) return <StatusDot tone="neutral">wyłączony</StatusDot>;
  if (!template.in_month) return <StatusDot tone="neutral">poza okresem ważności</StatusDot>;
  if (template.problem) {
    return (
      <StatusDot tone="warning" note={template.problem}>
        nie da się wystawić
      </StatusDot>
    );
  }
  if (template.address_missing) {
    return (
      <StatusDot tone="info" note="Uzupełnij adres w szablonie albo w szkicu.">
        brak adresu nabywcy
      </StatusDot>
    );
  }
  return <StatusDot tone="neutral">do wystawienia</StatusDot>;
}

/**
 * „Szablony” (E6): faktury „co miesiąc” bez zamówienia w NEXUSIE — usługi
 * i refaktury benefitów (pakiet sportowy, opieka medyczna) do kontraktorów.
 * Zaznaczone szablony dają szkice za wybrany miesiąc (jeden szkic szablonu na
 * miesiąc); szkic idzie dalej zwykłą drogą do KSeF.
 */
export function TemplatesPanel({
  period,
  onCreated,
}: {
  period: string;
  onCreated: (ids: number[]) => void;
}) {
  const { showToast } = useToast();
  const { year, month } = splitPeriod(period);
  const [kind, setKind] = useState<TemplateKind | null>(null);
  const query = useTemplates(kind, period);
  const run = useRunTemplates();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<InvoiceTemplate | "new" | null>(null);
  const [importing, setImporting] = useState(false);
  const templates = useMemo(() => query.data?.templates ?? [], [query.data]);
  const ready = templates.filter((template) => template.selectable);
  const total = ready
    .filter((template) => selected.has(template.id) && template.currency === "PLN")
    .reduce((sum, template) => sum + Number(template.net ?? 0), 0);

  const toggle = (id: number, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const submit = () =>
    run.mutate(
      { year, month, template_ids: [...selected] },
      {
        onSuccess: (result) => {
          showToast(
            `Utworzono ${countPl(result.created.length, "szkic", "szkice", "szkiców")}`,
            "success",
          );
          setSelected(new Set());
          onCreated(result.created);
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się utworzyć szkiców."), "error"),
      },
    );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2">
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Rodzaj szablonu">
          {FILTERS.map((filter) => (
            <Button
              key={filter.label}
              size="sm"
              variant={kind === filter.value ? "secondary" : "ghost"}
              aria-pressed={kind === filter.value}
              onClick={() => {
                setKind(filter.value);
                setSelected(new Set());
              }}
            >
              {filter.label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setImporting(true)}>
            <Download className="h-4 w-4" aria-hidden />
            Szablony z faktur z KSeF
          </Button>
          <Button size="sm" variant="outline" onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" aria-hidden />
            Nowy szablon
          </Button>
        </div>
      </div>

      {query.isLoading ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie szablonów…</p>
      ) : query.isError ? (
        <QueryStateNotice state="error" onRetry={() => query.refetch()} />
      ) : query.isSuccess && templates.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Nie ma jeszcze szablonów. Utwórz je z faktur, które eBI24 wystawił w poprzednim miesiącu
          („Szablony z faktur z KSeF”), albo dodaj ręcznie.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <p className="text-sm text-muted-foreground">
              {monthTitlePl(period)}: {countPl(ready.length, "szablon", "szablony", "szablonów")} do
              wystawienia.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={ready.length === 0}
                onClick={() => setSelected(new Set(ready.map((template) => template.id)))}
              >
                Zaznacz wszystkie do wystawienia
              </Button>
              <Button size="sm" onClick={submit} disabled={selected.size === 0 || run.isPending}>
                {run.isPending
                  ? "Tworzenie…"
                  : `Utwórz szkice${selected.size ? ` (${selected.size})` : ""}`}
              </Button>
            </div>
          </div>
          <div className="rounded-lg border border-border bg-card">
            <Table density="compact" className="table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead className={`${CALM_HEAD} w-10`}>
                    <span className="sr-only">Zaznacz</span>
                  </TableHead>
                  <TableHead className={`${CALM_HEAD} w-[28%]`}>Nabywca</TableHead>
                  <TableHead className={`${CALM_HEAD} w-[14%]`}>Rodzaj</TableHead>
                  <TableHead className={`${CALM_HEAD} w-[26%]`}>Pozycje</TableHead>
                  <TableHead className={`${CALM_HEAD} w-[12%] text-right`}>Netto</TableHead>
                  <TableHead className={`${CALM_HEAD} w-[20%]`}>Stan</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {templates.map((template) => (
                  <TableRow
                    key={template.id}
                    className={`${CALM_ROW} cursor-pointer align-top`}
                    data-testid={`template-${template.id}`}
                    onClick={() => setEditing(template)}
                  >
                    <TableCell onClick={(event) => event.stopPropagation()}>
                      <Checkbox
                        aria-label={`Zaznacz szablon ${template.name}`}
                        checked={selected.has(template.id)}
                        disabled={!template.selectable}
                        onCheckedChange={(value) => toggle(template.id, value === true)}
                      />
                    </TableCell>
                    <TableCell className="min-w-0">
                      <span className="block truncate" title={template.name}>
                        {template.name}
                      </span>
                      <span className={CALM_SUBLINE}>{template.buyer.number || "bez NIP-u"}</span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {template.kind === "benefit" ? template.benefit_label : template.kind_label}
                    </TableCell>
                    <TableCell className="min-w-0 text-sm">
                      <span className="block truncate" title={template.lines[0]?.name}>
                        {template.lines[0]?.name ?? "—"}
                      </span>
                      {template.lines.length > 1 ? (
                        <span className={CALM_SUBLINE}>
                          + {countPl(template.lines.length - 1, "pozycja", "pozycje", "pozycji")}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className={CALM_AMOUNT}>
                      {template.net ? formatMoney(template.net, template.currency) : "—"}
                    </TableCell>
                    <TableCell className="min-w-0" onClick={(event) => event.stopPropagation()}>
                      <TemplateState template={template} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {selected.size > 0 && total > 0 ? (
            <p className="px-1 text-right text-xs text-muted-foreground">
              Zaznaczone w PLN: {formatMoney(total.toFixed(2), "PLN")} netto
            </p>
          ) : null}
        </>
      )}

      {editing ? (
        <TemplateDialog
          template={editing === "new" ? null : editing}
          defaultKind={kind ?? "service"}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {importing ? <ImportTemplatesDialog period={period} onClose={() => setImporting(false)} /> : null}
    </div>
  );
}

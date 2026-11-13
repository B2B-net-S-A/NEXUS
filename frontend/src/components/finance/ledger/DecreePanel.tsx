"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDecreeRecalculate,
  useDecreeSave,
  type DecreeSection,
  type PositionKind,
  type Register,
  type Side,
} from "@/lib/api/finance-posting";
import { cn } from "@/lib/utils";

import {
  KIND_LABELS,
  REGISTER_LABELS,
  checkDraft,
  draftFromSection,
  draftToInput,
  emptyRow,
  formatGrosze,
  toGrosze,
  type Draft,
  type DraftRow,
} from "./posting-model";

const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";
const CONTROL =
  "h-8 rounded-md border border-border bg-background px-2 text-sm pointer-coarse:h-10";

function Positions({ section }: { section: DecreeSection }) {
  if (section.positions.length === 0) return null;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-muted-foreground">
          <th className="py-1 font-medium">Konto</th>
          <th className="py-1 font-medium">Pozycja</th>
          <th className="py-1 text-right font-medium">Wn</th>
          <th className="py-1 text-right font-medium">Ma</th>
        </tr>
      </thead>
      <tbody>
        {section.positions.map((position, index) => (
          <tr key={`${position.kind}-${index}`} className="border-t border-border align-top">
            <td className="py-1 pr-2">
              <span className="font-mono text-[12.5px]">{position.account ?? "—"}</span>
              {position.account_name ? (
                <span className="block text-xs text-muted-foreground">{position.account_name}</span>
              ) : null}
            </td>
            <td className="py-1 pr-2 text-muted-foreground">
              {position.kind_label}
              {position.vat_rate ? ` · ${position.vat_rate}%` : ""}
              {position.deduction_label ? ` · odliczenie ${position.deduction_label}` : ""}
            </td>
            <td className="py-1 text-right tabular-nums">
              {position.side === "debit" ? formatGrosze(toGrosze(position.amount) ?? 0) : ""}
            </td>
            <td className="py-1 text-right tabular-nums">
              {position.side === "credit" ? formatGrosze(toGrosze(position.amount) ?? 0) : ""}
            </td>
          </tr>
        ))}
        <tr className="border-t border-border font-semibold">
          <td className="py-1" colSpan={2}>
            Razem
          </td>
          <td className="py-1 text-right tabular-nums">
            {formatGrosze(toGrosze(section.debit_total) ?? 0)}
          </td>
          <td className="py-1 text-right tabular-nums">
            {formatGrosze(toGrosze(section.credit_total) ?? 0)}
          </td>
        </tr>
      </tbody>
    </table>
  );
}

function RowEditor({
  row,
  index,
  onChange,
  onRemove,
}: {
  row: DraftRow;
  index: number;
  onChange: (row: DraftRow) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={`Pozycja ${index + 1}`}>
      <select
        aria-label="Rodzaj pozycji"
        value={row.kind}
        onChange={(event) => onChange({ ...row, kind: event.target.value as PositionKind })}
        className={CONTROL}
      >
        {(Object.keys(KIND_LABELS) as PositionKind[]).map((kind) => (
          <option key={kind} value={kind}>
            {KIND_LABELS[kind]}
          </option>
        ))}
      </select>
      <Input
        aria-label="Konto"
        placeholder="Konto"
        value={row.account}
        onChange={(event) => onChange({ ...row, account: event.target.value })}
        className="h-8 w-28 font-mono text-[12.5px]"
      />
      <select
        aria-label="Strona"
        value={row.side}
        onChange={(event) => onChange({ ...row, side: event.target.value as Side })}
        className={CONTROL}
      >
        <option value="debit">Wn</option>
        <option value="credit">Ma</option>
      </select>
      <Input
        aria-label="Kwota"
        placeholder="0,00"
        inputMode="decimal"
        value={row.amount}
        onChange={(event) => onChange({ ...row, amount: event.target.value })}
        className="h-8 w-28 text-right tabular-nums"
      />
      <Button size="sm" variant="ghost" onClick={onRemove} aria-label={`Usuń pozycję ${index + 1}`}>
        Usuń
      </Button>
    </div>
  );
}

/** Ręczna korekta dekretu: zapis tylko przy bilansie Wn = Ma. */
export function DecreeEditor({
  entryId,
  section,
  onDone,
}: {
  entryId: number;
  section: DecreeSection;
  onDone: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFromSection(section));
  const save = useDecreeSave(entryId);
  const { showToast } = useToast();
  const check = checkDraft(draft);
  const setRow = (index: number, row: DraftRow) =>
    setDraft((current) => ({
      ...current,
      rows: current.rows.map((item, i) => (i === index ? row : item)),
    }));
  return (
    <div className="space-y-2" aria-label="Korekta dekretu">
      <div className="flex flex-wrap items-center gap-1.5">
        <select
          aria-label="Rejestr"
          value={draft.register}
          onChange={(event) =>
            setDraft((current) => ({ ...current, register: event.target.value as Register }))
          }
          className={CONTROL}
        >
          {(Object.keys(REGISTER_LABELS) as Register[]).map((register) => (
            <option key={register} value={register}>
              {REGISTER_LABELS[register]}
            </option>
          ))}
        </select>
        <Input
          aria-label="Typ dokumentu"
          value={draft.doc_type}
          maxLength={8}
          onChange={(event) => setDraft((current) => ({ ...current, doc_type: event.target.value }))}
          className="h-8 w-20 font-mono uppercase"
        />
        <Input
          aria-label="Opis"
          placeholder="Opis"
          value={draft.description}
          maxLength={255}
          onChange={(event) =>
            setDraft((current) => ({ ...current, description: event.target.value }))
          }
          className="h-8 min-w-0 flex-1"
        />
      </div>
      {draft.rows.map((row, index) => (
        <RowEditor
          key={row.key}
          row={row}
          index={index}
          onChange={(next) => setRow(index, next)}
          onRemove={() =>
            setDraft((current) => ({
              ...current,
              rows: current.rows.filter((_, i) => i !== index),
            }))
          }
        />
      ))}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Button
          size="sm"
          variant="outline"
          onClick={() => setDraft((current) => ({ ...current, rows: [...current.rows, emptyRow()] }))}
        >
          Dodaj pozycję
        </Button>
        <span className={cn("tabular-nums", check.balanced ? "text-muted-foreground" : "text-destructive")}>
          Wn {formatGrosze(check.debit)} · Ma {formatGrosze(check.credit)}
        </span>
      </div>
      {check.problems.length > 0 ? (
        <ul className="space-y-0.5 text-xs text-destructive" aria-label="Do poprawy">
          {check.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
        <Button
          size="sm"
          disabled={check.problems.length > 0}
          loading={save.isPending}
          onClick={() =>
            save.mutate(draftToInput(draft), {
              onSuccess: () => {
                showToast("Dekret zapisany.", "success");
                onDone();
              },
              onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać dekretu."), "error"),
            })
          }
        >
          Zapisz dekret
        </Button>
      </div>
    </div>
  );
}

/** Karta faktury → „Dekret do Symfonii FK” (makieta M2). */
export function DecreePanel({
  entryId,
  section,
  readOnly,
}: {
  entryId: number;
  section: DecreeSection;
  readOnly: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const recalc = useDecreeRecalculate(entryId);
  const { showToast } = useToast();
  const canEdit = section.editable && !readOnly;
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-3.5" aria-label="Dekret do Symfonii FK">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className={LABEL}>Dekret do Symfonii FK</h2>
        {section.manual ? <Badge size="sm" variant="info">ręczny</Badge> : null}
        {section.batch ? (
          <Badge size="sm" variant={section.batch.status === "booked" ? "success" : "soft"}>
            paczka {section.batch.number}
          </Badge>
        ) : null}
      </div>
      {section.computed ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Rejestr</dt>
          <dd>
            {section.register_label ?? "—"}
            {section.doc_type ? ` · ${section.doc_type}` : ""}
          </dd>
          <dt className="text-muted-foreground">Opis</dt>
          <dd className="min-w-0 break-words">{section.description ?? "—"}</dd>
          <dt className="text-muted-foreground">Reguła</dt>
          <dd>{section.manual ? "korekta ręczna" : (section.rule?.label ?? "—")}</dd>
        </dl>
      ) : null}
      {editing ? (
        <DecreeEditor entryId={entryId} section={section} onDone={() => setEditing(false)} />
      ) : (
        <Positions section={section} />
      )}
      {!editing && section.issues.length > 0 ? (
        <ul
          className="space-y-0.5 rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
          aria-label="Co blokuje księgowanie"
        >
          {section.issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      ) : null}
      {canEdit && !editing ? (
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            size="sm"
            variant="outline"
            loading={recalc.isPending}
            onClick={() =>
              recalc.mutate(undefined, {
                onSuccess: () => showToast("Dekret przeliczony z reguły.", "success"),
                onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przeliczyć."), "error"),
              })
            }
          >
            Przelicz
          </Button>
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            Popraw ręcznie
          </Button>
        </div>
      ) : null}
    </section>
  );
}

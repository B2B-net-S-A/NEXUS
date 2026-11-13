"use client";

import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useChart,
  useCreateDocument,
  useUpdateDocument,
  type DocumentCard,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

import { checkDraft, gr, newLine, type DraftLine } from "./ledger-model";

const CONTROL =
  "h-8 w-full min-w-0 rounded-md border border-border bg-background px-2 text-sm pointer-coarse:h-10";
const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

function fromCard(card: DocumentCard): DraftLine[] {
  return card.lines.map((line) => ({
    ...newLine(line.side),
    account: line.account,
    amount: (line.amount / 100).toFixed(2).replace(".", ","),
    description: line.description,
  }));
}

/**
 * Nowe albo poprawiane polecenie księgowania (PK) lub bilans otwarcia (BO).
 * Sumy i problemy liczy `checkDraft` tak jak serwer; zapis idzie do bufora,
 * zatwierdza osoba z listy „Księgowi”.
 */
export function DocumentForm({
  open,
  onOpenChange,
  defaultDate,
  editing,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultDate: string;
  editing?: DocumentCard | null;
  onSaved: (id: number) => void;
}) {
  const { showToast } = useToast();
  const chart = useChart(open);
  const create = useCreateDocument();
  const update = useUpdateDocument(editing?.id ?? 0);
  const [docType, setDocType] = useState<"PK" | "BO">(
    editing?.doc_type === "BO" ? "BO" : "PK",
  );
  const [opDate, setOpDate] = useState(editing?.op_date ?? defaultDate);
  const [docDate, setDocDate] = useState(editing?.doc_date ?? defaultDate);
  const [number, setNumber] = useState(editing?.number ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [lines, setLines] = useState<DraftLine[]>(() =>
    editing ? fromCard(editing) : [newLine("debit"), newLine("credit")],
  );
  const check = useMemo(() => checkDraft(lines), [lines]);
  // Problemy pokazujemy dopiero po pierwszej zmianie pozycji — pusty formularz
  // nie świeci na czerwono, zanim ktoś cokolwiek wpisze.
  const [touched, setTouched] = useState(Boolean(editing));
  const postable = useMemo(
    () => (chart.data ?? []).filter((account) => account.active && (account.postable || account.dictionary)),
    [chart.data],
  );
  const saving = create.isPending || update.isPending;

  const patch = (key: string, changes: Partial<DraftLine>) => {
    setTouched(true);
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...changes } : line)));
  };

  const submit = () => {
    if (check.problems.length) return;
    const body = {
      doc_type: docType,
      number: number.trim() || null,
      op_date: opDate,
      doc_date: docDate || opDate,
      description,
      lines: check.lines,
    };
    const done = {
      onSuccess: (card: DocumentCard) => {
        showToast(editing ? "Zapisano zmiany w buforze." : `Dodano ${card.number} do bufora.`);
        onSaved(card.id);
        onOpenChange(false);
      },
      onError: (error: unknown) => showToast(apiErrorMessage(error, "Nie udało się zapisać dokumentu."), "error"),
    };
    if (editing) update.mutate(body, done);
    else create.mutate(body, done);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{editing ? `Popraw ${editing.number}` : "Nowy dokument w buforze"}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-4">
            <label className="space-y-1">
              <span className={LABEL}>Typ</span>
              <select
                className={CONTROL}
                value={docType}
                disabled={Boolean(editing)}
                onChange={(event) => setDocType(event.target.value as "PK" | "BO")}
              >
                <option value="PK">PK — polecenie księgowania</option>
                <option value="BO">BO — bilans otwarcia</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Data operacji</span>
              <input type="date" className={CONTROL} value={opDate} onChange={(e) => setOpDate(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Data dokumentu</span>
              <input type="date" className={CONTROL} value={docDate} onChange={(e) => setDocDate(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className={LABEL}>Numer (opcjonalnie)</span>
              <input
                className={CONTROL}
                value={number}
                maxLength={80}
                placeholder="nadamy sami"
                onChange={(e) => setNumber(e.target.value)}
              />
            </label>
          </div>
          <label className="block space-y-1">
            <span className={LABEL}>Opis</span>
            <input
              className={CONTROL}
              value={description}
              maxLength={300}
              placeholder="np. przeksięgowanie kosztów najmu"
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <div className="rounded-md border border-border">
            <div className="grid grid-cols-[72px_minmax(0,1.1fr)_minmax(0,0.7fr)_minmax(0,1.4fr)_32px] gap-2 border-b border-border/70 px-2.5 py-1.5">
              <span className={LABEL}>Strona</span>
              <span className={LABEL}>Konto</span>
              <span className={cn(LABEL, "text-right")}>Kwota, zł</span>
              <span className={LABEL}>Treść</span>
              <span />
            </div>
            <datalist id="ledger-accounts">
              {postable.map((account) => (
                <option key={account.id} value={account.dictionary ? `${account.number}-` : account.number}>
                  {account.name}
                  {account.dictionary ? ` — analityka: ${account.dictionary_label}` : ""}
                </option>
              ))}
            </datalist>
            <div className="space-y-1.5 px-2.5 py-2">
              {lines.map((line, index) => (
                <div
                  key={line.key}
                  className="grid grid-cols-[72px_minmax(0,1.1fr)_minmax(0,0.7fr)_minmax(0,1.4fr)_32px] items-center gap-2"
                >
                  <select
                    aria-label={`Strona pozycji ${index + 1}`}
                    className={CONTROL}
                    value={line.side}
                    onChange={(e) => patch(line.key, { side: e.target.value as DraftLine["side"] })}
                  >
                    <option value="debit">Wn</option>
                    <option value="credit">Ma</option>
                  </select>
                  <input
                    aria-label={`Konto pozycji ${index + 1}`}
                    className={cn(CONTROL, "font-mono text-[13px]")}
                    list="ledger-accounts"
                    value={line.account}
                    placeholder="np. 402-203"
                    onChange={(e) => patch(line.key, { account: e.target.value })}
                  />
                  <input
                    aria-label={`Kwota pozycji ${index + 1}`}
                    className={cn(CONTROL, "text-right tabular-nums")}
                    inputMode="decimal"
                    value={line.amount}
                    placeholder="0,00"
                    onChange={(e) => patch(line.key, { amount: e.target.value })}
                  />
                  <input
                    aria-label={`Treść pozycji ${index + 1}`}
                    className={CONTROL}
                    value={line.description}
                    maxLength={200}
                    onChange={(e) => patch(line.key, { description: e.target.value })}
                  />
                  <button
                    type="button"
                    aria-label={`Usuń pozycję ${index + 1}`}
                    disabled={lines.length <= 2}
                    onClick={() => setLines((current) => current.filter((item) => item.key !== line.key))}
                    className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t border-border/70 px-2.5 py-2">
              <Button size="sm" variant="ghost" onClick={() => setLines((c) => [...c, newLine("debit")])}>
                <Plus className="mr-1 h-3.5 w-3.5" /> Wn
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setLines((c) => [...c, newLine("credit")])}>
                <Plus className="mr-1 h-3.5 w-3.5" /> Ma
              </Button>
              <span className="ml-auto text-[13px] tabular-nums">
                Wn <b>{gr(check.debit)}</b> · Ma <b>{gr(check.credit)}</b>{" "}
                <span className={check.balanced ? "text-success" : "text-destructive"}>
                  {check.balanced ? "= zgodne" : "≠ różnica " + gr(Math.abs(check.debit - check.credit))}
                </span>
              </span>
            </div>
          </div>
          {touched && check.problems.length ? (
            <p role="status" className="text-[12.5px] text-destructive">
              {check.problems[0]}
            </p>
          ) : null}
          <p className="text-[12px] text-muted-foreground">
            Konta ze słownikiem (np. kontrahenci) przyjmują analitykę: wpisz numer z dopiskiem, np. 201-2-1042. Storno
            czerwone: kwota z minusem po tej samej stronie.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button loading={saving} disabled={check.problems.length > 0} onClick={submit}>
            {editing ? "Zapisz w buforze" : "Dodaj do bufora"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

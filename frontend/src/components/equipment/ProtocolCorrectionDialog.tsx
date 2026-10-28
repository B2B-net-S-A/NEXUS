"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCorrectProtocol,
  type EquipmentProtocol,
  type ProtocolFix,
  type ProtocolLine,
  type ProtocolLineFix,
  type ReturnCondition,
} from "@/lib/api/equipment";
import { formatIsoDatePl } from "@/lib/date-pl";

import { CONDITION_LABELS } from "./equipment-format";

/** Karta SIM i karta dostępu są w protokole bez wartości (D6). */
const NO_VALUE: ReadonlySet<string> = new Set(["karta_sim", "karta_dostepu"]);
const AMOUNT = /^\d{1,7}(\.\d{1,2})?$/;

interface LineDraft {
  value: string;
  accessories: string;
  condition: ReturnCondition | null;
  notes: string;
}

function draftOf(line: ProtocolLine): LineDraft {
  return {
    value: line.unit_value == null ? "" : line.unit_value.replace(".", ","),
    accessories: line.accessories ?? "",
    condition: line.condition,
    notes: line.notes ?? "",
  };
}

/** „2 589,50” → „2589.50”; puste = bez wartości; zły zapis = `undefined`. */
export function parseAmount(text: string): string | null | undefined {
  const normalized = text.replace(/[\s ]/g, "").replace(",", ".");
  if (normalized === "") return null;
  return AMOUNT.test(normalized) ? normalized : undefined;
}

function sameAmount(a: string | null, b: string | null): boolean {
  if (a === null || b === null) return a === b;
  return Number(a) === Number(b);
}

/**
 * Poprawka protokołu przed podpisem (decyzja Artura 28.10.2026): data, imię
 * i nazwisko w protokole, per pozycja wartość i dodatki (wydanie) albo stan
 * i uwagi (zwrot). Wysyła tylko zmienione pola; zapis unieważnia wysłany link.
 */
export function ProtocolCorrectionDialog({
  protocol,
  onClose,
  onSaved,
  onCancelProtocol,
}: {
  protocol: EquipmentProtocol;
  onClose: () => void;
  onSaved: (result: { linkRevoked: boolean }) => void;
  onCancelProtocol: () => void;
}) {
  const correct = useCorrectProtocol();
  const lines = protocol.lines ?? [];
  const issue = protocol.kind === "wydanie";
  const [date, setDate] = useState(protocol.protocol_date);
  const [holderName, setHolderName] = useState(protocol.holder.name);
  const [drafts, setDrafts] = useState<Record<number, LineDraft>>(() =>
    Object.fromEntries(lines.map((line) => [line.position, draftOf(line)])),
  );
  const [error, setError] = useState<string | null>(null);
  const activeLink = protocol.link && !protocol.link.used_at ? protocol.link : null;

  const patchLine = (position: number, patch: Partial<LineDraft>) =>
    setDrafts((current) => ({ ...current, [position]: { ...current[position], ...patch } }));

  const buildFix = (): ProtocolFix | string => {
    const fix: ProtocolFix = {};
    if (date && date !== protocol.protocol_date) fix.protocol_date = date;
    const name = holderName.trim().replace(/\s+/g, " ");
    if (name.length < 3) return "Wpisz imię i nazwisko w protokole.";
    if (name !== protocol.holder.name) fix.holder_name = name;
    const lineFixes: ProtocolLineFix[] = [];
    for (const line of lines) {
      const draft = drafts[line.position];
      const change: ProtocolLineFix = { position: line.position };
      if (issue) {
        if (!NO_VALUE.has(line.category)) {
          const amount = parseAmount(draft.value);
          if (amount === undefined) {
            return `Pozycja ${line.position}: wpisz kwotę, np. 2589,00 (puste = bez wartości).`;
          }
          if (!sameAmount(amount, line.unit_value)) change.unit_value = amount;
        }
        const accessories = draft.accessories.trim().replace(/\s+/g, " ");
        if (line.base_name != null && accessories !== (line.accessories ?? "")) {
          change.accessories = accessories;
        }
      } else {
        if (draft.condition && draft.condition !== line.condition) change.condition = draft.condition;
        const notes = draft.notes.trim().replace(/\s+/g, " ");
        if (notes !== (line.notes ?? "")) change.notes = notes || null;
      }
      if (Object.keys(change).length > 1) lineFixes.push(change);
    }
    if (lineFixes.length) fix.lines = lineFixes;
    return fix;
  };

  const save = () => {
    const fix = buildFix();
    if (typeof fix === "string") {
      setError(fix);
      return;
    }
    if (Object.keys(fix).length === 0) {
      onClose();
      return;
    }
    setError(null);
    correct.mutate(
      { protocolId: protocol.id, fix },
      {
        onSuccess: (data) => onSaved({ linkRevoked: data.link_revoked }),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać poprawek.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={`Popraw protokół ${protocol.number}`}
      description={`${issue ? "Wydanie" : "Zwrot"} · przed podpisem. Numer protokołu zostaje.`}
      size="xl"
      footer={
        <>
          <Button
            variant="ghost"
            className="text-destructive hover:bg-destructive/10 sm:mr-auto"
            onClick={onCancelProtocol}
            disabled={correct.isPending}
          >
            Anuluj protokół…
          </Button>
          <Button variant="outline" onClick={onClose} disabled={correct.isPending}>
            Zamknij
          </Button>
          <Button onClick={save} loading={correct.isPending}>
            Zapisz poprawki
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        {activeLink ? (
          <p
            role="note"
            className="flex items-start gap-2 rounded-md border border-border bg-muted/40 p-3 text-xs"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            <span>
              Link do podpisu wysłany {formatIsoDatePl(activeLink.created_at)} przestanie działać po
              zapisie — osoba nie podpisze starej treści. Nowy link utworzysz zaraz po zapisie.
            </span>
          </p>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-[12rem_minmax(0,1fr)]">
          <FormField label="Data protokołu" htmlFor={`eq-fix-date-${protocol.id}`}>
            <Input
              id={`eq-fix-date-${protocol.id}`}
              type="date"
              className="h-9"
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
          </FormField>
          <FormField
            label="Imię i nazwisko w protokole"
            htmlFor={`eq-fix-holder-${protocol.id}`}
            description="Tylko zapis w tym protokole. Nazwa konta się nie zmienia."
          >
            <Input
              id={`eq-fix-holder-${protocol.id}`}
              className="h-9"
              maxLength={200}
              value={holderName}
              onChange={(event) => setHolderName(event.target.value)}
            />
          </FormField>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="py-1 pr-2 text-left">Lp.</th>
                <th className="py-1 pr-2 text-left">Nazwa sprzętu</th>
                <th className="py-1 pr-2 text-left">{issue ? "Dodatki" : "Stan"}</th>
                <th className={`py-1 text-left ${issue ? "w-36" : ""}`}>
                  {issue ? "Wartość (zł)" : "Uwagi"}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {lines.map((line) => {
                const draft = drafts[line.position];
                return (
                  <tr key={line.position} className="align-top">
                    <td className="py-2 pr-2">{line.position}</td>
                    <td className="py-2 pr-2">
                      <span className="block">{issue ? (line.base_name ?? line.name) : line.name}</span>
                      {line.identifier ? (
                        <span className="block font-mono text-xs text-muted-foreground">
                          {line.identifier}
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2 pr-2">
                      {issue ? (
                        line.base_name != null ? (
                          <Input
                            aria-label={`Dodatki, pozycja ${line.position}`}
                            className="h-8"
                            placeholder="np. zasilacz, mysz"
                            maxLength={200}
                            value={draft.accessories}
                            onChange={(event) =>
                              patchLine(line.position, { accessories: event.target.value })
                            }
                          />
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            Nazwa w rejestrze zmieniła się po wydaniu
                          </span>
                        )
                      ) : (
                        <Select
                          value={draft.condition ?? undefined}
                          onValueChange={(value) =>
                            patchLine(line.position, { condition: value as ReturnCondition })
                          }
                        >
                          <SelectTrigger
                            aria-label={`Stan, pozycja ${line.position}`}
                            className="h-8 w-56"
                          >
                            <SelectValue placeholder="Wybierz stan" />
                          </SelectTrigger>
                          <SelectContent>
                            {(Object.keys(CONDITION_LABELS) as ReturnCondition[]).map((value) => (
                              <SelectItem key={value} value={value}>
                                {CONDITION_LABELS[value]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    </td>
                    <td className="py-2">
                      {issue ? (
                        NO_VALUE.has(line.category) ? (
                          <span className="text-xs text-muted-foreground">bez wartości</span>
                        ) : (
                          <Input
                            aria-label={`Wartość, pozycja ${line.position}`}
                            className="h-8 text-right tabular-nums"
                            inputMode="decimal"
                            value={draft.value}
                            onChange={(event) =>
                              patchLine(line.position, { value: event.target.value })
                            }
                          />
                        )
                      ) : (
                        <Input
                          aria-label={`Uwagi, pozycja ${line.position}`}
                          className="h-8"
                          maxLength={500}
                          value={draft.notes}
                          onChange={(event) =>
                            patchLine(line.position, { notes: event.target.value })
                          }
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">
          Pozycji nie dodaje się ani nie usuwa. Gdy sprzęt jest nie ten albo czegoś brakuje,
          anuluj protokół i wydaj sprzęt jeszcze raz.
        </p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}

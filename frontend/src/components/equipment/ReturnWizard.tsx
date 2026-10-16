"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
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
  useHolderEquipment,
  useReturnEquipment,
  type EquipmentHolder,
  type EquipmentProtocol,
  type ReturnCondition,
} from "@/lib/api/equipment";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import { CONDITION_LABELS, assignmentLabel, formatDatePl } from "./equipment-format";
import { HolderPicker } from "./HolderPicker";
import { ProtocolDownloads } from "./ProtocolDownloads";

interface ReturnWizardProps {
  onClose: () => void;
  presetHolder?: EquipmentHolder | null;
}

interface Choice {
  selected: boolean;
  condition: ReturnCondition;
  notes: string;
}

const CONDITIONS = Object.keys(CONDITION_LABELS) as ReturnCondition[];

/** „Przyjmij zwrot”: osoba → jej sprzęt ze stanem przy zwrocie → protokół zwrotu. */
export function ReturnWizard({ onClose, presetHolder = null }: ReturnWizardProps) {
  const [holder, setHolder] = useState<EquipmentHolder | null>(presetHolder);
  const equipment = useHolderEquipment(holder?.kind ?? null, holder?.id ?? null);
  const [choices, setChoices] = useState<Record<number, Choice>>({});
  const [date, setDate] = useState(() => warsawToday());
  const [error, setError] = useState<string | null>(null);
  const [protocol, setProtocol] = useState<EquipmentProtocol | null>(null);
  const returning = useReturnEquipment();

  const active = equipment.data?.active ?? [];
  const state = resolveViewState({
    isLoading: equipment.isLoading,
    error: equipment.error,
    isSuccess: equipment.isSuccess,
    isEmpty: active.length === 0,
  });
  const choiceOf = (id: number): Choice =>
    choices[id] ?? { selected: true, condition: "sprawny", notes: "" };
  const update = (id: number, patch: Partial<Choice>) =>
    setChoices((prev) => ({ ...prev, [id]: { ...choiceOf(id), ...patch } }));
  const selected = active.filter((row) => choiceOf(row.assignment_id).selected);

  const submit = () => {
    setError(null);
    returning.mutate(
      {
        protocol_date: date || null,
        lines: selected.map((row) => {
          const choice = choiceOf(row.assignment_id);
          return {
            assignment_id: row.assignment_id,
            condition: choice.condition,
            notes: choice.notes.trim() || null,
          };
        }),
      },
      {
        onSuccess: (data) => setProtocol(data.protocol),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się przyjąć zwrotu.")),
      },
    );
  };

  if (protocol) {
    return (
      <AppModal
        open
        onOpenChange={(next) => {
          if (!next) onClose();
        }}
        title={`Zwrot przyjęty · protokół ${protocol.number}`}
        description="Stan pozycji zmieniony. Wydrukuj protokół zwrotu do podpisu."
        footer={<Button onClick={onClose}>Gotowe</Button>}
      >
        <ProtocolDownloads protocol={protocol} />
      </AppModal>
    );
  }

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={holder ? `Przyjmij zwrot · ${holder.name}` : "Przyjmij zwrot"}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            disabled={!holder || selected.length === 0 || returning.isPending}
            onClick={submit}
          >
            {returning.isPending
              ? "Zapisywanie…"
              : `Przyjmij zwrot (${selected.length})`}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {presetHolder ? null : <HolderPicker value={holder} onChange={setHolder} />}
        {holder ? (
          state === "loading" ? (
            <p className="text-sm text-muted-foreground">Wczytywanie sprzętu osoby…</p>
          ) : state === "forbidden" || state === "not_found" || state === "error" ? (
            <QueryStateNotice state={state} onRetry={() => equipment.refetch()} />
          ) : state === "empty" ? (
            <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              Ta osoba nie ma wydanego sprzętu w rejestrze.
            </p>
          ) : (
            <>
              <ul className="divide-y divide-border rounded-md border border-border">
                {active.map((row) => {
                  const choice = choiceOf(row.assignment_id);
                  return (
                    <li key={row.assignment_id} className="space-y-2 px-3 py-2 text-sm">
                      <label className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={choice.selected}
                          onChange={(event) =>
                            update(row.assignment_id, { selected: event.target.checked })
                          }
                        />
                        <span className="min-w-0">
                          <span className="block font-medium">{assignmentLabel(row)}</span>
                          <span className="block text-xs text-muted-foreground">
                            wydany {formatDatePl(row.issued_at)}
                            {row.issue_protocol ? ` · ${row.issue_protocol}` : ""}
                            {row.ownership === "klienta" ? " · sprzęt klienta" : ""}
                          </span>
                        </span>
                      </label>
                      {choice.selected ? (
                        <div className="flex gap-2 pl-6">
                          <Select
                            value={choice.condition}
                            onValueChange={(value) =>
                              update(row.assignment_id, { condition: value as ReturnCondition })
                            }
                          >
                            <SelectTrigger
                              aria-label={`Stan przy zwrocie: ${row.model_name}`}
                              className="h-8 w-56 text-xs"
                            >
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {CONDITIONS.map((condition) => (
                                <SelectItem key={condition} value={condition}>
                                  {CONDITION_LABELS[condition]}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Input
                            aria-label={`Uwagi: ${row.model_name}`}
                            placeholder="Uwagi (np. rysa na obudowie)"
                            value={choice.notes}
                            onChange={(event) =>
                              update(row.assignment_id, { notes: event.target.value })
                            }
                            className="h-8 text-xs"
                          />
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
              <FormField label="Data protokołu zwrotu" htmlFor="eq-return-date">
                <Input
                  id="eq-return-date"
                  type="date"
                  value={date}
                  onChange={(event) => setDate(event.target.value)}
                  className="w-44"
                />
              </FormField>
              <p className="text-xs text-muted-foreground">
                Uszkodzony sprzęt trafia do serwisu, zgubiony dostaje stan „Zgubiony”. Pozycje
                z zakładki „Sprzęt” kontraktu zmieniają się na „Zwrócony”.
              </p>
            </>
          )
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}

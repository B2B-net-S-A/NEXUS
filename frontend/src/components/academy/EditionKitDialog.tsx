"use client";

/**
 * „Wydaj zestawy” edycji Akademii: ten sam zestaw (modele z cennika) kilku
 * uczestnikom naraz. NEXUS proponuje egzemplarze po numerze ewidencyjnym,
 * recepcja może je zamienić; każdy uczestnik dostaje osobny protokół, a odmowa
 * jednej osoby (np. pozycję ktoś właśnie wydał) nie cofa pozostałych.
 */

import { useMemo, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { CATEGORY_LABELS, itemNumber } from "@/components/equipment/equipment-format";
import { ProtocolLinkBox } from "@/components/equipment/ProtocolLinkBox";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  useIssueEditionKits,
  type BulkIssueReport,
  type EditionParticipant,
  type EditionRef,
} from "@/lib/api/academy-edition";
import { useEquipmentItems } from "@/lib/api/equipment";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import {
  assignItem,
  freeModels,
  itemsOfModel,
  kitPayload,
  proposeKits,
  splitComplete,
  type KitPlan,
} from "./edition-kit";

interface EditionKitDialogProps {
  edition: EditionRef;
  participants: readonly EditionParticipant[];
  onClose: () => void;
}

const NONE = "__none__";

export function EditionKitDialog({ edition, participants, onClose }: EditionKitDialogProps) {
  const free = useEquipmentItems({ free: true });
  const issue = useIssueEditionKits(edition);
  const [step, setStep] = useState<"kit" | "plan">("kit");
  const [modelIds, setModelIds] = useState<number[]>([]);
  const [plan, setPlan] = useState<KitPlan>({});
  const [date, setDate] = useState(() => warsawToday());
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<BulkIssueReport | null>(null);

  const items = useMemo(() => free.data?.items ?? [], [free.data]);
  const models = useMemo(() => freeModels(items), [items]);
  const people = participants.map((p) => p.application_id);
  const { ready, incomplete } = splitComplete(plan, modelIds);
  const names = new Map(participants.map((p) => [p.application_id, p.full_name]));
  const state = resolveViewState({
    isLoading: free.isLoading,
    error: free.error,
    isSuccess: free.isSuccess,
    isEmpty: models.length === 0,
  });

  const toggleModel = (modelId: number, on: boolean) =>
    setModelIds((prev) => (on ? [...prev, modelId] : prev.filter((id) => id !== modelId)));

  const goToPlan = () => {
    setPlan(proposeKits(people, modelIds, items));
    setStep("plan");
  };

  const submit = (sendLink: boolean) => {
    setError(null);
    issue.mutate(
      {
        protocol_date: date || null,
        send_link: sendLink,
        participants: kitPayload(plan, modelIds, ready),
      },
      {
        onSuccess: (data) => setReport(data),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się wydać zestawów.")),
      },
    );
  };

  if (report) {
    return (
      <AppModal
        open
        onOpenChange={(next) => {
          if (!next) onClose();
        }}
        title={`Wydano zestawy: ${report.issued} z ${report.issued + report.failed}`}
        description="Każdy uczestnik ma osobny protokół, który czeka na podpis."
        size="lg"
        footer={<Button onClick={onClose}>Gotowe</Button>}
      >
        <ul className="space-y-3 text-sm">
          {report.results.map((result) => (
            <li key={result.application_id} className="space-y-1.5">
              <p className="font-medium">{names.get(result.application_id) ?? "Uczestnik"}</p>
              {result.ok ? (
                result.link_url ? (
                  <ProtocolLinkBox
                    url={result.link_url}
                    number={result.protocol.number}
                    email={result.protocol.holder.email}
                  />
                ) : (
                  <p className="text-muted-foreground">
                    Protokół {result.protocol.number} — do wydruku i podpisu na papierze.
                  </p>
                )
              ) : (
                <p role="alert" className="text-destructive">
                  Nie wydano: {result.message}
                </p>
              )}
            </li>
          ))}
        </ul>
      </AppModal>
    );
  }

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={`Wydaj zestawy · ${participants.length} os.`}
      description={
        step === "kit"
          ? "Wybierz modele, z których składa się zestaw — każdy uczestnik dostanie po jednej sztuce."
          : "Sprawdź przydział egzemplarzy. Każda osoba dostanie osobny protokół."
      }
      size="xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          {step === "kit" ? (
            <Button disabled={modelIds.length === 0} onClick={goToPlan}>
              Dalej: przydział
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => setStep("kit")}>
                Wstecz
              </Button>
              <Button
                variant="outline"
                disabled={ready.length === 0 || issue.isPending}
                onClick={() => submit(false)}
              >
                Wydaj, podpis na papierze
              </Button>
              <Button disabled={ready.length === 0 || issue.isPending} onClick={() => submit(true)}>
                {issue.isPending ? "Zapisywanie…" : `Wydaj i utwórz linki (${ready.length})`}
              </Button>
            </>
          )}
        </>
      }
    >
      {step === "kit" ? (
        state === "loading" ? (
          <p className="text-sm text-muted-foreground">Wczytywanie wolnego sprzętu…</p>
        ) : state === "forbidden" || state === "not_found" || state === "error" ? (
          <QueryStateNotice state={state} onRetry={() => free.refetch()} />
        ) : state === "empty" ? (
          <p className="text-sm text-muted-foreground">Brak wolnego sprzętu na stanie.</p>
        ) : (
          <ul className="max-h-[50dvh] divide-y divide-border overflow-y-auto rounded-md border border-border">
            {models.map((model) => {
              const id = `kit-model-${model.modelId}`;
              const short = model.free < participants.length;
              return (
                <li key={model.modelId} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <Checkbox
                    id={id}
                    checked={modelIds.includes(model.modelId)}
                    onCheckedChange={(checked) => toggleModel(model.modelId, checked === true)}
                  />
                  <label htmlFor={id} className="min-w-0 flex-1 cursor-pointer">
                    <span className="block truncate">
                      {CATEGORY_LABELS[model.category]} {model.name}
                    </span>
                  </label>
                  <span
                    className={
                      short ? "text-xs text-destructive" : "text-xs text-muted-foreground"
                    }
                  >
                    wolnych {model.free}
                    {short ? ` · potrzeba ${participants.length}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        )
      ) : (
        <div className="space-y-3">
          <FormField label="Data protokołów" htmlFor="kit-date">
            <Input
              id="kit-date"
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              className="w-44"
            />
          </FormField>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 text-left">Uczestnik</th>
                  {modelIds.map((modelId) => {
                    const model = models.find((m) => m.modelId === modelId);
                    return (
                      <th key={modelId} className="px-3 py-1.5 text-left">
                        {model ? `${CATEGORY_LABELS[model.category]} ${model.name}` : "—"}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {participants.map((person) => (
                  <tr key={person.application_id}>
                    <td className="px-3 py-1.5">
                      <span className="block font-medium">{person.full_name}</span>
                      {incomplete.includes(person.application_id) ? (
                        <span className="block text-xs text-destructive">
                          Brakuje sprzętu — bez wydania
                        </span>
                      ) : null}
                    </td>
                    {modelIds.map((modelId) => {
                      const chosen = plan[person.application_id]?.[modelId] ?? null;
                      return (
                        <td key={modelId} className="px-3 py-1.5">
                          <Select
                            value={chosen == null ? NONE : String(chosen)}
                            onValueChange={(value) =>
                              setPlan((prev) =>
                                assignItem(
                                  prev,
                                  person.application_id,
                                  modelId,
                                  value === NONE ? null : Number(value),
                                ),
                              )
                            }
                          >
                            <SelectTrigger
                              aria-label={`${person.full_name}: egzemplarz`}
                              className="h-8 w-32 text-xs"
                            >
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={NONE}>bez tej pozycji</SelectItem>
                              {itemsOfModel(items, modelId).map((item) => (
                                <SelectItem key={item.id} value={String(item.id)}>
                                  {itemNumber(item)}
                                  {item.serial_number ? ` · ${item.serial_number}` : ""}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            Wartości pozycji w protokołach pochodzą z cennika. Osoby bez kompletu zestawu nie
            dostaną nic — wydasz im sprzęt, gdy będzie na stanie.
          </p>
        </div>
      )}
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

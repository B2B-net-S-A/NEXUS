"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CALENDAR_RHYTHMS,
  FAMILY_LABELS,
  PREPARER_LABELS,
  RHYTHM_LABELS,
  createDefinition,
  getGenerators,
  updateDefinition,
  type DefinitionInput,
  type DueRule,
  type DueRuleType,
  type ReportDefinition,
  type ReportFamily,
  type ReportPreparer,
  type ReportRhythm,
} from "@/lib/api/client-reports";

const FIELD = "h-9 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground";
const DUE_TYPES: { value: DueRuleType; label: string }[] = [
  { value: "none", label: "Termin do ustalenia" },
  { value: "day_of_month", label: "Do N. dnia następnego miesiąca" },
  { value: "business_days_after", label: "N dni roboczych po okresie" },
  { value: "days_after", label: "N dni po okresie" },
  { value: "fixed", label: "Stała data (dzień i miesiąc)" },
  { value: "end_of_period", label: "Na koniec okresu" },
];

interface DefinitionFormDialogProps {
  clientId: number;
  definition: ReportDefinition | null;
  open: boolean;
  onClose: () => void;
}

function initial(definition: ReportDefinition | null): DefinitionInput {
  if (definition) {
    return {
      name: definition.name,
      family: definition.family,
      generator_key: definition.generator_key,
      params: definition.params,
      rhythm: definition.rhythm,
      due_rule: definition.due_rule?.type ? definition.due_rule : { type: "none" },
      recipient: definition.recipient,
      channel: definition.channel,
      file_format: definition.file_format,
      preparer: definition.preparer,
      preparer_user_id: definition.preparer_user_id,
      source_kind: definition.source_kind,
      source_contract_id: definition.source_contract_id,
      source_chunk_id: definition.source_chunk_id,
      source_ref: definition.source_ref,
      valid_from: definition.valid_from,
      valid_to: definition.valid_to,
      notes: definition.notes,
    };
  }
  return {
    name: "",
    family: "management",
    generator_key: null,
    params: {},
    rhythm: "monthly",
    due_rule: { type: "day_of_month", day: 5 },
    recipient: null,
    channel: "e-mail",
    file_format: "XLSX",
    preparer: "dl",
    source_kind: "dl",
    source_ref: null,
    valid_from: null,
    valid_to: null,
    notes: null,
  };
}

/** Dodanie albo zmiana raportu w katalogu klienta. */
export function DefinitionFormDialog({ clientId, definition, open, onClose }: DefinitionFormDialogProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [form, setForm] = useState<DefinitionInput>(() => initial(definition));
  const generators = useQuery({ queryKey: ["client-report-generators"], queryFn: getGenerators, enabled: open });

  const fitting = useMemo(
    () => (generators.data ?? []).filter((g) => g.rhythms.includes(form.rhythm)),
    [generators.data, form.rhythm],
  );
  const generator = fitting.find((g) => g.key === form.generator_key) ?? null;
  // Bez listy generatorów nie wiadomo, czy wybrany generator pasuje — zapis
  // wyzerowałby go (a raport BNP zniknąłby z Projektów). Czekamy na listę.
  const generatorsReady = generators.isSuccess;

  const set = <K extends keyof DefinitionInput>(key: K, value: DefinitionInput[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));
  const setDue = (patch: Partial<DueRule>) => setForm((prev) => ({ ...prev, due_rule: { ...prev.due_rule, ...patch } }));

  const save = useMutation({
    mutationFn: () => {
      const body: DefinitionInput = {
        ...form,
        name: form.name.trim(),
        generator_key: generator ? generator.key : null,
        params: generator ? form.params : {},
        recipient: form.recipient?.trim() || null,
        channel: form.channel?.trim() || null,
        file_format: form.file_format?.trim() || null,
        source_ref: form.source_ref?.trim() || null,
        notes: form.notes?.trim() || null,
      };
      return definition ? updateDefinition(definition.id, body) : createDefinition(clientId, body);
    },
    onSuccess: (saved) => {
      showSuccess(
        saved.status === "proposal"
          ? "Zapisano jako propozycję — zatwierdzi ją Delivery Lead klienta."
          : "Zapisano raport w katalogu.",
      );
      void queryClient.invalidateQueries({ queryKey: ["client-reports", clientId] });
      void queryClient.invalidateQueries({ queryKey: ["client-reports-calendar"] });
      onClose();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać raportu.")),
  });

  const due = form.due_rule;
  const needsNumber = due.type === "business_days_after" || due.type === "days_after";
  const canSave = form.name.trim().length > 0 && generatorsReady && !save.isPending;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{definition ? "Zmień raport" : "Dodaj raport klienta"}</DialogTitle>
          <DialogDescription>
            Co klient wymaga, jak często i do kiedy. Raport dodany przez osobę spoza zespołu klienta czeka na zatwierdzenie DL-a.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 sm:col-span-2">
            <span className="text-xs text-muted-foreground">Nazwa raportu</span>
            <Input id="report-name" value={form.name} maxLength={200} onChange={(e) => set("name", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Rodzaj</span>
            <select id="report-family" className={FIELD} value={form.family} onChange={(e) => set("family", e.target.value as ReportFamily)}>
              {(Object.keys(FAMILY_LABELS) as ReportFamily[]).map((key) => (
                <option key={key} value={key}>
                  {FAMILY_LABELS[key]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Rytm</span>
            <select id="report-rhythm" className={FIELD} value={form.rhythm} onChange={(e) => set("rhythm", e.target.value as ReportRhythm)}>
              {(Object.keys(RHYTHM_LABELS) as ReportRhythm[]).map((key) => (
                <option key={key} value={key}>
                  {RHYTHM_LABELS[key]}
                </option>
              ))}
            </select>
          </label>
          {CALENDAR_RHYTHMS.includes(form.rhythm) ? (
            <div className="grid gap-2 sm:col-span-2 sm:grid-cols-[1fr_auto_auto] sm:items-end">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Termin</span>
                <select id="report-due-type" className={FIELD} value={due.type} onChange={(e) => setForm((prev) => ({ ...prev, due_rule: { type: e.target.value as DueRuleType, anchor: prev.due_rule.anchor } }))}>
                  {DUE_TYPES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              {due.type === "day_of_month" || due.type === "fixed" ? (
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Dzień</span>
                  <Input id="report-due-day" type="number" min={1} max={31} className="w-20" value={due.day ?? ""} onChange={(e) => setDue({ day: Number(e.target.value) || undefined })} />
                </label>
              ) : null}
              {due.type === "fixed" ? (
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Miesiąc</span>
                  <Input id="report-due-month" type="number" min={1} max={12} className="w-20" value={due.month ?? ""} onChange={(e) => setDue({ month: Number(e.target.value) || undefined })} />
                </label>
              ) : null}
              {needsNumber ? (
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Dni</span>
                  <Input id="report-due-days" type="number" min={0} max={120} className="w-20" value={due.days ?? ""} onChange={(e) => setDue({ days: Number(e.target.value) })} />
                </label>
              ) : null}
              {form.rhythm === "contract_year" ? (
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Początek roku umowy (MM-DD)</span>
                  <Input id="report-due-anchor" placeholder="02-27" className="w-28" value={due.anchor ?? ""} onChange={(e) => setDue({ anchor: e.target.value || undefined })} />
                </label>
              ) : null}
            </div>
          ) : null}
          <label className="flex flex-col gap-1 sm:col-span-2">
            <span className="text-xs text-muted-foreground">Plik z NEXUSA</span>
            <select id="report-generator" className={FIELD} value={generator?.key ?? ""} onChange={(e) => setForm((prev) => ({ ...prev, generator_key: e.target.value || null, params: {} }))}>
              <option value="">Brak — plik przygotowany poza NEXUSEM</option>
              {fitting.map((g) => (
                <option key={g.key} value={g.key}>
                  {g.label}
                </option>
              ))}
            </select>
            {generator ? <span className="block text-xs text-muted-foreground">{generator.description}</span> : null}
            {generators.isPending ? <span className="block text-xs text-muted-foreground">Wczytuję listę plików z NEXUSA…</span> : null}
            {generators.isError ? (
              <span className="block text-xs text-destructive">
                {apiErrorMessage(generators.error, "Nie udało się wczytać listy plików z NEXUSA — zapis jest wstrzymany.")}
              </span>
            ) : null}
          </label>
          {generator?.params
            .filter((param) => param.kind === "bool")
            .map((param) => (
              <label key={param.key} className="flex items-center gap-2 text-sm sm:col-span-2">
                <input
                  id={`report-param-${param.key}`}
                  type="checkbox"
                  checked={Boolean(form.params[param.key] ?? param.default)}
                  onChange={(e) => set("params", { ...form.params, [param.key]: e.target.checked })}
                />
                {param.label}
                {param.hint ? <span className="text-xs text-muted-foreground">— {param.hint}</span> : null}
              </label>
            ))}
          {generator?.params
            .filter((param) => param.kind === "text")
            .map((param) => (
              <label key={param.key} className="space-y-1">
                <span className="text-xs text-muted-foreground">{param.label}</span>
                <Input id={`report-param-${param.key}`} value={String(form.params[param.key] ?? param.default ?? "")} onChange={(e) => set("params", { ...form.params, [param.key]: e.target.value })} />
              </label>
            ))}
          {generator?.params.some((param) => param.kind === "tiers") ? (
            <TiersField
              value={(form.params.tiers as { up_to: number | null; rate: number }[] | undefined) ?? []}
              onChange={(tiers) => set("params", { ...form.params, tiers })}
            />
          ) : null}
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Odbiorca po stronie klienta (rola)</span>
            <Input id="report-recipient" value={form.recipient ?? ""} maxLength={255} onChange={(e) => set("recipient", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Przygotowuje</span>
            <select id="report-preparer" className={FIELD} value={form.preparer} onChange={(e) => set("preparer", e.target.value as ReportPreparer)}>
              {(Object.keys(PREPARER_LABELS) as ReportPreparer[]).map((key) => (
                <option key={key} value={key}>
                  {PREPARER_LABELS[key]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Kanał</span>
            <Input id="report-channel" value={form.channel ?? ""} maxLength={32} onChange={(e) => set("channel", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Źródło (paragraf albo ustalenie)</span>
            <Input id="report-source-ref" value={form.source_ref ?? ""} maxLength={255} onChange={(e) => set("source_ref", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Obowiązuje od</span>
            <Input id="report-valid-from" type="date" value={form.valid_from ?? ""} onChange={(e) => set("valid_from", e.target.value || null)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Obowiązuje do</span>
            <Input id="report-valid-to" type="date" value={form.valid_to ?? ""} onChange={(e) => set("valid_to", e.target.value || null)} />
          </label>
          <label className="flex flex-col gap-1 sm:col-span-2">
            <span className="text-xs text-muted-foreground">Uwagi</span>
            <Textarea id="report-notes" rows={2} value={form.notes ?? ""} maxLength={4000} onChange={(e) => set("notes", e.target.value)} />
          </label>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={() => save.mutate()} disabled={!canSave} loading={save.isPending}>
            Zapisz
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TiersField({
  value,
  onChange,
}: {
  value: { up_to: number | null; rate: number }[];
  onChange: (tiers: { up_to: number | null; rate: number }[]) => void;
}) {
  const rows = value.length ? value : [{ up_to: null, rate: 0 }];
  const update = (index: number, patch: Partial<{ up_to: number | null; rate: number }>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  return (
    <fieldset className="space-y-1 sm:col-span-2">
      <legend className="text-xs text-muted-foreground">Progi rabatu (górna granica obrotu, puste = bez górnej granicy)</legend>
      {rows.map((row, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            id={`report-tier-up-${index}`}
            type="number"
            min={0}
            placeholder="do kwoty"
            className="w-40"
            value={row.up_to ?? ""}
            onChange={(e) => update(index, { up_to: e.target.value ? Number(e.target.value) : null })}
          />
          <Input
            id={`report-tier-rate-${index}`}
            type="number"
            min={0}
            max={100}
            step={0.1}
            className="w-24"
            value={row.rate}
            onChange={(e) => update(index, { rate: Number(e.target.value) })}
          />
          <span className="text-xs text-muted-foreground">%</span>
          <Button variant="quiet" size="sm" onClick={() => onChange(rows.filter((_, i) => i !== index))} disabled={rows.length === 1}>
            Usuń
          </Button>
        </div>
      ))}
      <Button variant="ghost" size="sm" onClick={() => onChange([...rows, { up_to: null, rate: 0 }])} disabled={rows.length >= 6}>
        Dodaj próg
      </Button>
    </fieldset>
  );
}

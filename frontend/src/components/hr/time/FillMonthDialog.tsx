"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import type { EmploymentType } from "@/lib/api/hr";
import type { FillInput, FillResult, TimesheetTemplate } from "@/lib/api/hr-time";
import { monthTitlePl, type YearMonth } from "@/lib/date-pl";
import { employmentTerms } from "@/lib/hr-employment-terms";

import { formatHours, parseHours } from "./time-format";

const MAX_FILL_HOURS = 8;

type Source = "default" | "template" | "custom";

export interface RoleDefaultHint {
  label: string;
  description: string;
  project: string | null;
}

export interface FillMonthDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  period: YearMonth;
  templates: readonly TimesheetTemplate[];
  /** Domyślny opis Kadr dla roli osoby (`GET /me/templates` → `role_default`). */
  roleDefault: RoleDefaultHint | null;
  onFill: (payload: FillInput) => Promise<FillResult>;
  onDone: (result: FillResult) => void;
  /** Forma osoby: przy B2B i zleceniu „godziny ponad 8 h” zamiast „nadgodzin”. */
  form?: EmploymentType | null;
}

/** Ciało żądania z pól okna (czysta funkcja — test bez renderu). */
export function fillPayload(input: {
  hours: number;
  source: Source;
  templateId: number | null;
  description: string;
  project: string;
  overwrite: boolean;
}): FillInput {
  const payload: FillInput = { hours_per_day: input.hours, overwrite: input.overwrite };
  if (input.source === "template" && input.templateId != null) {
    payload.template_id = input.templateId;
  }
  if (input.source === "custom") payload.description = input.description.trim();
  const project = input.project.trim();
  if (project) payload.project = project;
  return payload;
}

/**
 * „Wypełnij miesiąc” z oknem (jak Compass): godziny dziennie (domyślnie 8,
 * najwyżej 8 — nadgodziny wpisuje się w dniu, z uzasadnieniem), opis
 * domyślny roli, z szablonu albo własny, projekt i „nadpisz istniejące
 * wpisy”. Dni urlopu, święta i dni wolne firmy pomija serwer.
 */
export function FillMonthDialog({
  open,
  onOpenChange,
  period,
  templates,
  roleDefault,
  onFill,
  onDone,
  form,
}: FillMonthDialogProps) {
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [hours, setHours] = useState("8");
  const [source, setSource] = useState<Source>("default");
  const [templateId, setTemplateId] = useState<number | null>(templates[0]?.id ?? null);
  const [description, setDescription] = useState("");
  const [project, setProject] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const template = templates.find((item) => item.id === templateId) ?? null;
  // Bez szablonu i domyślnego opisu Kadr — słowo formy (jak serwer).
  const defaultText = roleDefault?.description ?? employmentTerms(form).standard_description;
  const projectHint =
    source === "template" ? template?.project : source === "default" ? roleDefault?.project : null;
  const monthName = monthTitlePl(period).toLowerCase();

  const submit = async () => {
    setError(null);
    const parsed = parseHours(hours);
    if (parsed == null || parsed <= 0 || parsed > MAX_FILL_HOURS) {
      setError(
        `Wypełnianie wpisuje od 0,01 do ${MAX_FILL_HOURS} h dziennie — ${employmentTerms(form).overtime_fill_note}.`,
      );
      return;
    }
    if (source === "template" && template == null) {
      setError("Wybierz szablon.");
      return;
    }
    if (source === "custom" && !description.trim()) {
      setError("Wpisz opis.");
      return;
    }
    if (overwrite) {
      const ok = await askConfirm({
        title: `Nadpisać wpisy za ${monthName}?`,
        description:
          "Wpisy z tego miesiąca znikną i miesiąc wypełni się od nowa. Auto-wpisy płatnych dni z puli zostają.",
        confirmLabel: "Nadpisz i wypełnij",
        variant: "destructive",
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      const result = await onFill(
        fillPayload({ hours: parsed, source, templateId, description, project, overwrite }),
      );
      onDone(result);
      onOpenChange(false);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się wypełnić miesiąca."));
    } finally {
      setBusy(false);
    }
  };

  const sourceOptions = [
    { value: "default" as const, label: "Domyślny" },
    {
      value: "template" as const,
      label: "Mój szablon",
      disabled: templates.length === 0,
      title: templates.length === 0 ? "Nie masz jeszcze szablonów opisów." : undefined,
    },
    { value: "custom" as const, label: "Własny opis" },
  ];

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Wypełnij ${monthName}`}
      description="Wpisy na każdy dzień roboczy bez wpisu. Weekendy, święta, dni wolne firmy i nieobecności zostają puste."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={busy}>
            {busy ? "Wypełnianie…" : "Wypełnij"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-[140px_minmax(0,1fr)]">
        <FormField
          label="Godziny dziennie"
          htmlFor="time-fill-hours"
          description={`Najwyżej ${MAX_FILL_HOURS} h.`}
        >
          <Input
            id="time-fill-hours"
            inputMode="decimal"
            value={hours}
            onChange={(event) => setHours(event.target.value)}
          />
        </FormField>
        <FormField
          label="Projekt"
          htmlFor="time-fill-project"
          description={projectHint ? `Puste = ${projectHint}.` : "Opcjonalnie."}
        >
          <Input
            id="time-fill-project"
            value={project}
            maxLength={200}
            onChange={(event) => setProject(event.target.value)}
          />
        </FormField>
        <div className="space-y-2 sm:col-span-2">
          <span id="time-fill-source" className="text-sm font-medium text-foreground">
            Opis
          </span>
          <SegmentedRadio
            labelledBy="time-fill-source"
            value={source}
            onChange={setSource}
            options={sourceOptions}
          />
          {source === "default" ? (
            <p className="text-sm text-muted-foreground">
              {roleDefault ? `${roleDefault.label}: ` : ""}„{defaultText}”
            </p>
          ) : source === "template" ? (
            <>
              <Select
                value={templateId != null ? String(templateId) : undefined}
                onValueChange={(value) => setTemplateId(Number(value))}
              >
                <SelectTrigger id="time-fill-template" aria-label="Szablon">
                  <SelectValue placeholder="Wybierz szablon" />
                </SelectTrigger>
                <SelectContent>
                  {templates.map((item) => (
                    <SelectItem key={item.id} value={String(item.id)}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {template ? (
                <p className="text-sm text-muted-foreground">„{template.description}”</p>
              ) : null}
            </>
          ) : (
            <Textarea
              id="time-fill-description"
              aria-label="Własny opis"
              rows={2}
              maxLength={2000}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          )}
        </div>
        <label className="flex items-start gap-2 text-sm sm:col-span-2">
          <Checkbox
            checked={overwrite}
            aria-label="Nadpisz istniejące wpisy"
            onCheckedChange={(checked) => setOverwrite(checked === true)}
            className="mt-0.5"
          />
          <span>
            Nadpisz istniejące wpisy
            <span className="block text-xs text-muted-foreground">
              {overwrite
                ? `Wpisy za ${monthName} znikną, a każdy dzień roboczy dostanie ${formatHours(parseHours(hours))} h. Auto-wpisy płatnych dni z puli zostają.`
                : "Bez zaznaczenia dni, które mają już wpis, zostają bez zmian."}
            </span>
          </span>
        </label>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {confirmDialog}
    </AppModal>
  );
}

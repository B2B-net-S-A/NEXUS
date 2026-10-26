"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  SERVICE_LINE_LABELS,
  useCreateOpportunity,
  type OpportunityDetail,
  type OpportunityRole,
  type Ref,
  type ServiceLine,
} from "@/lib/api/sales";

import { CompanyPicker } from "./CompanyPicker";
import { SalesSelect } from "./SalesSelect";

interface OpportunityFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Firma z karty firmy — wtedy nie wybieramy jej drugi raz. */
  company?: Ref;
  onCreated?: (opportunity: OpportunityDetail) => void;
}

const SERVICE_OPTIONS = Object.entries(SERVICE_LINE_LABELS).map(([value, label]) => ({
  value,
  label,
}));

/** Kwota z pola formularza: „40 000,50” → „40000.50”; puste → null. */
export function parseAmount(raw: string): string | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!cleaned) return null;
  return /^\d+(\.\d{1,2})?$/.test(cleaned) ? cleaned : null;
}

/** Role z jednej linii: „3 × Java Developer, 2 × QA” → [{count, title}]. */
export function parseRoles(raw: string): OpportunityRole[] {
  return raw
    .split(/[,;\n]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const match = part.match(/^(\d+)\s*[x×*]\s*(.+)$/i);
      return match
        ? { count: Number(match[1]), title: match[2].trim() }
        : { count: 1, title: part };
    });
}

export function OpportunityFormDialog({
  open,
  onOpenChange,
  company,
  onCreated,
}: OpportunityFormDialogProps) {
  const [picked, setPicked] = useState<Ref | null>(company ?? null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [serviceLine, setServiceLine] = useState<ServiceLine | "">("bodyleasing");
  const [mrr, setMrr] = useState("");
  const [oneOff, setOneOff] = useState("");
  const [months, setMonths] = useState("");
  const [closeDate, setCloseDate] = useState("");
  const [roles, setRoles] = useState("");
  const create = useCreateOpportunity();
  const { showError, showSuccess } = useToast();

  const submit = () => {
    if (!picked) {
      showError("Wybierz firmę z kartoteki sprzedaży.");
      return;
    }
    if (!title.trim()) {
      showError("Podaj nazwę szansy.");
      return;
    }
    const mrrValue = parseAmount(mrr);
    const oneOffValue = parseAmount(oneOff);
    if ((mrr.trim() && !mrrValue) || (oneOff.trim() && !oneOffValue)) {
      showError("Kwotę wpisz liczbą, np. 40000 albo 40 000,50.");
      return;
    }
    create.mutate(
      {
        company_id: picked.id,
        title: title.trim(),
        description: description.trim() || null,
        service_line: serviceLine || null,
        mrr_value: mrrValue,
        one_off_value: oneOffValue,
        contract_months: months ? Number(months) : null,
        expected_close_date: closeDate || null,
        roles: parseRoles(roles),
      },
      {
        onSuccess: (opportunity) => {
          showSuccess("Dodano szansę. Uzupełniamy daty osób z tej firmy w tle.");
          onCreated?.(opportunity);
          onOpenChange(false);
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać szansy.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Nowa szansa"
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={create.isPending}>
            Anuluj
          </Button>
          <Button onClick={submit} loading={create.isPending}>
            Dodaj szansę
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-opp-company">Firma</Label>
          {company ? (
            <p id="sales-opp-company" className="text-sm">{company.name}</p>
          ) : (
            <CompanyPicker id="sales-opp-company" value={picked} onChange={setPicked} />
          )}
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-opp-title">Nazwa szansy</Label>
          <Input
            id="sales-opp-title"
            value={title}
            placeholder="np. zespół QA i automatyzacji"
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-opp-line">Model współpracy</Label>
          <SalesSelect
            id="sales-opp-line"
            value={serviceLine}
            onValueChange={(value) => setServiceLine(value as ServiceLine | "")}
            options={SERVICE_OPTIONS}
            anyLabel="Nie określono"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-opp-close">Planowane zamknięcie</Label>
          <Input
            id="sales-opp-close"
            type="date"
            value={closeDate}
            onChange={(event) => setCloseDate(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-opp-mrr">Miesięcznie (zł)</Label>
          <Input
            id="sales-opp-mrr"
            inputMode="decimal"
            value={mrr}
            onChange={(event) => setMrr(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-opp-oneoff">Jednorazowo (zł)</Label>
          <Input
            id="sales-opp-oneoff"
            inputMode="decimal"
            value={oneOff}
            onChange={(event) => setOneOff(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-opp-months">Okres umowy (mies.)</Label>
          <Input
            id="sales-opp-months"
            type="number"
            min={1}
            max={120}
            value={months}
            onChange={(event) => setMonths(event.target.value)}
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-opp-roles">Role, których szuka klient</Label>
          <Input
            id="sales-opp-roles"
            value={roles}
            placeholder="np. 3 × Test Automation, 2 × QA, 1 × lider"
            onChange={(event) => setRoles(event.target.value)}
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-opp-description">Opis</Label>
          <Textarea
            id="sales-opp-description"
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
      </div>
    </AppModal>
  );
}

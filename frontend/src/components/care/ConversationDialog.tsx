"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
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
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CHANNEL_LABELS,
  useAddConversation,
  type CareChannel,
  type CarePlanItem,
} from "@/lib/api/care";
import { warsawToday } from "@/lib/warsaw-date";

interface ConversationDialogProps {
  contractId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Punkt planu, który ta rozmowa zamyka (z „Zapisz” przy punkcie). */
  planItem?: CarePlanItem | null;
}

const NO_SCORE = "none";

/** „Zapisz rozmowę” — rozmowa z konsultantem bez danych o zdrowiu i stawek. */
export function ConversationDialog({
  contractId,
  open,
  onOpenChange,
  planItem,
}: ConversationDialogProps) {
  const { showToast } = useToast();
  const save = useAddConversation(contractId);
  const today = warsawToday();
  const [occurredOn, setOccurredOn] = useState(today);
  const [channel, setChannel] = useState<CareChannel>("phone");
  const [satisfaction, setSatisfaction] = useState(NO_SCORE);
  const [note, setNote] = useState("");
  const [attritionRisk, setAttritionRisk] = useState(false);
  const [wantsChange, setWantsChange] = useState(false);
  const [projectEnd, setProjectEnd] = useState("");
  const [clientHiring, setClientHiring] = useState(false);
  const [hiringNote, setHiringNote] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    if (!occurredOn || occurredOn > today) {
      setError("Podaj datę rozmowy (najpóźniej dzisiejszą).");
      return;
    }
    if (followUp && followUp < occurredOn) {
      setError("Następny kontakt musi być po dacie rozmowy.");
      return;
    }
    save.mutate(
      {
        occurred_on: occurredOn,
        channel,
        satisfaction: satisfaction === NO_SCORE ? null : Number(satisfaction),
        note: note.trim() || null,
        attrition_risk: attritionRisk,
        wants_change: wantsChange,
        project_end_on: projectEnd || null,
        client_hiring: clientHiring,
        client_hiring_note: clientHiring ? hiringNote.trim() || null : null,
        follow_up_on: followUp || null,
        plan_item_id: planItem?.id ?? null,
      },
      {
        onSuccess: () => {
          showToast("Rozmowa zapisana", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać rozmowy.")),
      },
    );
  };

  const flag = (
    id: string,
    label: string,
    checked: boolean,
    onChange: (value: boolean) => void,
  ) => (
    <label htmlFor={id} className="flex items-center gap-2 text-sm text-foreground">
      <Checkbox id={id} checked={checked} onCheckedChange={(value) => onChange(value === true)} />
      {label}
    </label>
  );

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zapisz rozmowę"
      description={
        planItem
          ? `Zamyka punkt planu: ${planItem.label}. Bez danych o zdrowiu i bez stawek.`
          : "Bez danych o zdrowiu i bez stawek — te mają swoje miejsca."
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz rozmowę"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <FormField label="Data" htmlFor="care-conv-date" required>
          <Input
            id="care-conv-date"
            type="date"
            value={occurredOn}
            max={today}
            onChange={(event) => setOccurredOn(event.target.value)}
          />
        </FormField>
        <FormField label="Forma" htmlFor="care-conv-channel">
          <Select value={channel} onValueChange={(value) => setChannel(value as CareChannel)}>
            <SelectTrigger id="care-conv-channel">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(CHANNEL_LABELS) as CareChannel[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {CHANNEL_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Zadowolenie" htmlFor="care-conv-score">
          <Select value={satisfaction} onValueChange={setSatisfaction}>
            <SelectTrigger id="care-conv-score">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_SCORE}>Bez oceny</SelectItem>
              {[5, 4, 3, 2, 1].map((score) => (
                <SelectItem key={score} value={String(score)}>
                  {score} / 5
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </div>
      <FormField label="Notatka" htmlFor="care-conv-note" className="mt-3">
        <Textarea
          id="care-conv-note"
          rows={4}
          maxLength={4000}
          value={note}
          placeholder="Jak mu się pracuje, co słychać w projekcie, czego potrzebuje."
          onChange={(event) => setNote(event.target.value)}
        />
      </FormField>
      <fieldset className="mt-3 grid gap-2 rounded-md border border-border/60 p-3">
        <legend className="px-1 text-xs font-medium text-muted-foreground">Sygnały</legend>
        {flag("care-conv-risk", "Ryzyko odejścia", attritionRisk, setAttritionRisk)}
        {flag("care-conv-change", "Chce zmiany projektu", wantsChange, setWantsChange)}
        {flag("care-conv-hiring", "Klient zatrudnia (sygnał popytu)", clientHiring, setClientHiring)}
        {clientHiring ? (
          <Input
            aria-label="Kogo szuka klient"
            value={hiringNote}
            maxLength={500}
            placeholder="np. dwóch testerów do zespołu płatności"
            onChange={(event) => setHiringNote(event.target.value)}
          />
        ) : null}
        <p className="text-xs text-muted-foreground">
          Ryzyko i chęć zmiany trafiają do kolejki „Do przepięcia”.
        </p>
      </fieldset>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <FormField
          label="Koniec projektu"
          htmlFor="care-conv-end"
          description="Jeśli konsultant wie, kiedy projekt się kończy."
        >
          <Input
            id="care-conv-end"
            type="date"
            value={projectEnd}
            onChange={(event) => setProjectEnd(event.target.value)}
          />
        </FormField>
        <FormField
          label="Następny kontakt"
          htmlFor="care-conv-follow"
          description="Przypomnienie przyjdzie do opiekuna w tym dniu."
        >
          <Input
            id="care-conv-follow"
            type="date"
            value={followUp}
            min={occurredOn}
            onChange={(event) => setFollowUp(event.target.value)}
          />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

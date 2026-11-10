"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { FormRow } from "@/components/ds/FormGroup";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useMoveOpportunity, useUpdateOpportunity, type OfferRow, type Stage } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";

import { plusDays } from "./CallLogDialogs";
import { SalesSelect } from "./SalesSelect";

const UNTIL: { label: string; days: number }[] = [
  { label: "Za tydzień", days: 7 },
  { label: "Za 2 tygodnie", days: 14 },
  { label: "Za miesiąc", days: 30 },
];
const DEFAULT_DAYS = 14;
const FORM_ROW = "sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-3 sm:py-2";

interface PostponeOfferDialogProps {
  offer: OfferRow;
  onClose: () => void;
}

/** „Odłóż do…”: oferta wraca do „W toku” i znów czeka na decyzję w wybranym dniu. */
export function PostponeOfferDialog({ offer, onClose }: PostponeOfferDialogProps) {
  const update = useUpdateOpportunity(offer.id);
  const { showError, showSuccess } = useToast();
  const [days, setDays] = useState<number | null>(DEFAULT_DAYS);
  const [date, setDate] = useState(plusDays(DEFAULT_DAYS));
  const tomorrow = plusDays(1);

  const save = () => {
    update.mutate(
      { keep_open_until: date },
      {
        onSuccess: () => {
          showSuccess(`Odłożono do ${formatIsoDatePl(date)}.`);
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się odłożyć oferty.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title="Odłóż do…"
      description={`${offer.company.name} · ${offer.title}`}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!date || date < tomorrow} loading={update.isPending} onClick={save}>
            Odłóż
          </Button>
        </>
      }
    >
      <FormRow label="Wróć do niej" htmlFor="sales-offer-until" className={FORM_ROW}>
        <div className="flex flex-wrap gap-1.5">
          {UNTIL.map((item) => (
            <Button
              key={item.label}
              size="sm"
              variant={days === item.days ? "primary" : "outline"}
              onClick={() => {
                setDays(item.days);
                setDate(plusDays(item.days));
              }}
            >
              {item.label}
            </Button>
          ))}
        </div>
        <Input
          id="sales-offer-until"
          type="date"
          value={date}
          min={tomorrow}
          onChange={(event) => {
            setDays(null);
            setDate(event.target.value);
          }}
        />
      </FormRow>
      <p className="text-xs text-muted-foreground">
        Do tego dnia oferta jest w „W toku”. Jeśli nic się przy niej nie wydarzy, wróci do „Do decyzji”.
      </p>
    </AppModal>
  );
}

interface CloseOfferDialogProps {
  offer: OfferRow;
  /** Etapy przegranej lejka tej szansy, domyślny pierwszy. */
  stages: readonly Stage[];
  onClose: () => void;
}

/** „Zamknij z powodem”: ta sama ścieżka co „Przegrana” na karcie, czyli `/move` na etap przegranej. */
export function CloseOfferDialog({ offer, stages, onClose }: CloseOfferDialogProps) {
  const move = useMoveOpportunity();
  const { showError, showSuccess } = useToast();
  const [chosenStage, setChosenStage] = useState("");
  const [reason, setReason] = useState("");
  // Lejki mogą dojść po otwarciu okna, więc domyślny etap nie siedzi w stanie.
  const stageId = chosenStage || String(stages[0]?.id ?? "");

  const save = () => {
    move.mutate(
      { id: offer.id, stage_id: Number(stageId), lost_reason: reason.trim() || undefined },
      {
        onSuccess: (moved) => {
          showSuccess(`Zamknięto na etapie „${moved.stage.name}”.`);
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zamknąć szansy.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title="Zamknij z powodem"
      description={`${offer.company.name} · ${offer.title}`}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!stageId} loading={move.isPending} onClick={save}>
            Zamknij szansę
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {stages.length === 0 && (
          <p role="alert" className="text-sm text-destructive">
            Nie udało się wczytać etapów tego lejka. Odśwież stronę i spróbuj ponownie.
          </p>
        )}
        {stages.length > 1 && (
          <div className="space-y-1">
            <Label htmlFor="sales-offer-lost-stage">Etap</Label>
            <SalesSelect
              id="sales-offer-lost-stage"
              value={stageId}
              onValueChange={setChosenStage}
              options={stages.map((stage) => ({ value: String(stage.id), label: stage.name }))}
            />
          </div>
        )}
        <div className="space-y-1">
          <Label htmlFor="sales-offer-lost-reason">Powód (opcjonalnie)</Label>
          <Textarea
            id="sales-offer-lost-reason"
            rows={3}
            value={reason}
            maxLength={500}
            placeholder="np. wybrali konkurencję, wstrzymany budżet, brak odpowiedzi"
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
      </div>
    </AppModal>
  );
}

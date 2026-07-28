"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  CheckCircle2,
  Clock3,
  PhoneMissed,
  PhoneOff,
} from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
  candidateContactApi,
  candidateContactFullName,
  candidateContactQueryKeys,
  buildCandidateContactAttemptInput,
  isCandidateContactVersionConflict,
  type CandidateContactAttemptInput,
  type CandidateContactCase,
  type CandidateContactOpportunityOutcome,
  type CandidateContactOutcome,
} from "@/lib/candidate-contact";
import { extractErrorMsg } from "@/lib/api";
import { cn } from "@/lib/utils";

const OUTCOMES: Array<{
  value: CandidateContactOutcome;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  {
    value: "connected",
    label: "Rozmowa odbyta",
    description: "Zapisz decyzję osobno dla każdej przedstawionej oferty.",
    icon: CheckCircle2,
  },
  {
    value: "no_answer",
    label: "Brak odpowiedzi",
    description: "System zaplanuje kolejną próbę zgodnie z regułami kolejki.",
    icon: PhoneMissed,
  },
  {
    value: "callback_requested",
    label: "Prośba o oddzwonienie",
    description: "Wymaga wskazania konkretnego terminu callbacku.",
    icon: Clock3,
  },
  {
    value: "wrong_number",
    label: "Błędny numer",
    description: "Kandydat trafi do wyjątków do czasu poprawienia numeru.",
    icon: PhoneOff,
  },
  {
    value: "do_not_contact",
    label: "Nie kontaktować",
    description: "Trwale blokuje automatyczne ponowne otwarcie kontaktu.",
    icon: Ban,
  },
];

const OPPORTUNITY_OUTCOMES: Array<{
  value: CandidateContactOpportunityOutcome;
  label: string;
}> = [
  { value: "interested", label: "Zainteresowany/a" },
  { value: "maybe", label: "Do namysłu" },
  { value: "not_interested", label: "Brak zainteresowania" },
  { value: "not_presented", label: "Nie przedstawiono" },
];

function freshIdempotencyKey(): string {
  if (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }
  return `contact-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export interface ContactOutcomeSheetProps {
  contactCase: CandidateContactCase | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (updated: CandidateContactCase) => void;
  onConflict?: () => void;
  submitAttempt?: (
    caseId: number,
    input: CandidateContactAttemptInput,
    idempotencyKey: string,
  ) => Promise<CandidateContactCase>;
}

export function ContactOutcomeSheet({
  contactCase,
  open,
  onOpenChange,
  onSaved,
  onConflict,
  submitAttempt = candidateContactApi.logAttempt,
}: ContactOutcomeSheetProps) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [outcome, setOutcome] =
    React.useState<CandidateContactOutcome | null>(null);
  const [callbackAt, setCallbackAt] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [opportunityOutcomes, setOpportunityOutcomes] = React.useState<
    Record<number, CandidateContactOpportunityOutcome>
  >({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [submitting, setSubmitting] = React.useState(false);
  const submittingRef = React.useRef(false);
  const idempotencyKey = React.useRef(freshIdempotencyKey());

  React.useEffect(() => {
    if (!open) return;
    setOutcome(null);
    setCallbackAt("");
    setNotes("");
    setOpportunityOutcomes({});
    setErrors({});
    setSubmitting(false);
    submittingRef.current = false;
    idempotencyKey.current = freshIdempotencyKey();
  }, [contactCase?.id, open]);

  if (!contactCase) return null;

  const needsOpportunityResults =
    outcome === "connected" || outcome === "callback_requested";
  const needsCallback =
    outcome === "callback_requested" ||
    (needsOpportunityResults &&
      Object.values(opportunityOutcomes).some(
        (value) => value === "maybe" || value === "not_presented",
      ));

  const validate = (): CandidateContactAttemptInput | null => {
    const validation = buildCandidateContactAttemptInput(contactCase, {
      outcome,
      callbackAt,
      notes,
      opportunityOutcomes,
    });
    setErrors(validation.errors);
    return validation.input;
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submittingRef.current) return;
    const payload = validate();
    if (!payload) return;

    submittingRef.current = true;
    setSubmitting(true);
    try {
      const updated = await submitAttempt(
        contactCase.id,
        payload,
        idempotencyKey.current,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: candidateContactQueryKeys.queue(),
        }),
        queryClient.invalidateQueries({
          queryKey: candidateContactQueryKeys.candidate(
            contactCase.candidate.id,
          ),
        }),
        queryClient.invalidateQueries({
          queryKey: candidateContactQueryKeys.oversight(),
        }),
        queryClient.invalidateQueries({ queryKey: ["candidates-v2"] }),
      ]);
      showSuccess("Wynik telefonu został zapisany.");
      onSaved?.(updated);
      onOpenChange(false);
    } catch (error) {
      if (isCandidateContactVersionConflict(error)) {
        setErrors({
          form: "Ktoś zmienił ten kontakt. Odśwież dane i spróbuj ponownie.",
        });
        onConflict?.();
      } else {
        showError(extractErrorMsg(error) || "Nie udało się zapisać wyniku.");
      }
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent size="lg">
        <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit}>
          <SheetHeader>
            <SheetTitle>Zaloguj wynik telefonu</SheetTitle>
            <SheetDescription>
              {candidateContactFullName(contactCase.candidate)} · jedna rozmowa
              może dotyczyć wszystkich otwartych rekrutacji.
            </SheetDescription>
          </SheetHeader>

          <SheetBody className="space-y-6">
            {errors.form ? (
              <div
                role="alert"
                className="rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
              >
                {errors.form}
              </div>
            ) : null}

            <FormField label="Wynik próby" required error={errors.outcome}>
              <RadioGroup
                value={outcome ?? ""}
                onValueChange={(value) => {
                  setOutcome(value as CandidateContactOutcome);
                  setErrors((current) => ({ ...current, outcome: "" }));
                }}
                className="gap-2"
              >
                {OUTCOMES.map((item) => {
                  const Icon = item.icon;
                  const selected = outcome === item.value;
                  return (
                    <label
                      key={item.value}
                      className={cn(
                        "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                        selected
                          ? "border-primary bg-primary/5"
                          : "border-border bg-card hover:bg-accent/50",
                        item.value === "do_not_contact" &&
                          selected &&
                          "border-destructive/40 bg-destructive-muted",
                      )}
                    >
                      <RadioGroupItem
                        value={item.value}
                        aria-label={item.label}
                        className="mt-0.5 shrink-0"
                      />
                      <Icon
                        aria-hidden
                        className={cn(
                          "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground",
                          selected && "text-primary",
                          item.value === "do_not_contact" &&
                            selected &&
                            "text-destructive",
                        )}
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-foreground">
                          {item.label}
                        </span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          {item.description}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </RadioGroup>
            </FormField>

            {needsOpportunityResults ? (
              <fieldset className="space-y-3">
                <legend className="text-sm font-medium text-foreground">
                  Wynik dla każdej rekrutacji
                </legend>
                {contactCase.opportunities.map((opportunity) => (
                  <div
                    key={opportunity.job_id}
                    className="rounded-lg border border-border bg-muted/30 p-3"
                  >
                    <div className="mb-2 min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">
                        {opportunity.job_title}
                      </p>
                      {opportunity.client_name ? (
                        <p className="truncate text-xs text-muted-foreground">
                          {opportunity.client_name}
                        </p>
                      ) : null}
                      {opportunity.owner ? (
                        <p className="truncate text-xs text-muted-foreground">
                          Właściciel rekrutacji: {opportunity.owner.name}
                        </p>
                      ) : null}
                    </div>
                    <Select
                      value={opportunityOutcomes[opportunity.job_id] ?? ""}
                      onValueChange={(value) => {
                        setOpportunityOutcomes((current) => ({
                          ...current,
                          [opportunity.job_id]:
                            value as CandidateContactOpportunityOutcome,
                        }));
                        setErrors((current) => ({
                          ...current,
                          [`job-${opportunity.job_id}`]: "",
                        }));
                      }}
                    >
                      <SelectTrigger
                        aria-label={`Wynik: ${opportunity.job_title}`}
                        invalid={Boolean(errors[`job-${opportunity.job_id}`])}
                      >
                        <SelectValue placeholder="Wybierz wynik" />
                      </SelectTrigger>
                      <SelectContent>
                        {OPPORTUNITY_OUTCOMES.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {errors[`job-${opportunity.job_id}`] ? (
                      <p
                        role="alert"
                        className="mt-1.5 text-xs font-medium text-primary"
                      >
                        {errors[`job-${opportunity.job_id}`]}
                      </p>
                    ) : null}
                  </div>
                ))}
              </fieldset>
            ) : null}

            {needsCallback ? (
              <FormField
                htmlFor="candidate-contact-callback"
                label="Termin callbacku"
                required
                error={errors.callback_at}
                description="Termin zapisuje backend; kolejka pokaże go jako callback."
              >
                <Input
                  id="candidate-contact-callback"
                  type="datetime-local"
                  value={callbackAt}
                  onChange={(event) => {
                    setCallbackAt(event.target.value);
                    setErrors((current) => ({
                      ...current,
                      callback_at: "",
                    }));
                  }}
                  invalid={Boolean(errors.callback_at)}
                />
              </FormField>
            ) : null}

            <FormField
              htmlFor="candidate-contact-notes"
              label="Notatka"
              description="Opcjonalny kontekst do audytu kontaktu."
            >
              <Textarea
                id="candidate-contact-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Krótka notatka z rozmowy…"
                rows={3}
              />
            </FormField>
          </SheetBody>

          <SheetFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Anuluj
            </Button>
            <Button type="submit" loading={submitting}>
              Zapisz wynik
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}

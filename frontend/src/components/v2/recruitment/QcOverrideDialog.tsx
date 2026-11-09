"use client";

/**
 * „Przepuść mimo QC” (decyzja Artura 02.10.2026): cztery gotowe powody, opis
 * wymagany tylko przy „Inny powód”, bez minimum znaków. Do 02.10 pole
 * wymagało 10 znaków i zbierało wpisy bez treści. Okno mówi wprost, z czym
 * CV pójdzie dalej. Tylko osoby z uprawnieniem „Rekrutacje: zakładanie,
 * zamykanie, wysyłka CV do klienta” (serwer odmawia reszcie).
 *
 * Tryb doradczy (`advisory`, 12.10.2026): to samo okno z tytułem „Przesuń mimo
 * uwag QC” — otwiera je także rekruter z rekrutacji, a Delivery Lead dostaje
 * powiadomienie. Powody i walidacja są te same.
 *
 * „Kandydat potwierdził to w rozmowie” (D3, 17.10.2026) zapisuje po stronie
 * serwera „Potwierdzone z kandydatem” przy rzeczach bez źródła — okno to mówi.
 *
 * „Inny powód” (R6, 07.11.2026): co najmniej trzy słowa i zaznaczenie, której
 * uwagi dotyczy (`about_keys`), gdy rzeczy mają klucze pozycji. 15 z 91 obejść
 * w 30 dniach miało powód „x”, „.” albo „dw”.
 */

import { useId, useState } from "react";
import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { useQcOverride, type QcResult } from "@/lib/api/cvQc";
import {
  QC_OVERRIDE_NOTE_MAX,
  QC_OVERRIDE_POINTS_AT_ITEM,
  QC_OVERRIDE_REASONS,
  countForm,
  qcOverrideError,
  type QcOverrideReason,
  type QcPendingItem,
} from "@/lib/cv-qc";
import { cn } from "@/lib/utils";

/** Ile niepoprawionych rzeczy wymieniamy z nazwy — reszta jako „i N innych”. */
const PENDING_SHOWN = 4;

export interface QcOverrideDialogProps {
  stageId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Tytuły rzeczy, które zostają niepoprawione. */
  pending: string[];
  /**
   * Te same rzeczy z kluczami pozycji (D4, 17.10.2026): przy blokadzie wybór
   * „Prawda” (domyślnie) / „QC się myli” — ten drugi idzie do „Jakość QC”.
   */
  pendingItems?: readonly QcPendingItem[];
  onChanged?: () => void;
  /** QC doradza, nie blokuje — inne nazwy tytułu, opisu i przycisku. */
  advisory?: boolean;
  /** Po zapisaniu powodu, ze świeżym wynikiem QC (np. od razu „Przesuń dalej”). */
  onDone?: (result: QcResult) => void;
}

export function overrideSummary(count: number): string {
  if (count <= 0) return "CV pójdzie dalej mimo wyniku QC.";
  return count === 1
    ? "CV pójdzie dalej z 1 niepoprawioną rzeczą:"
    : `CV pójdzie dalej z ${count} niepoprawionymi rzeczami:`;
}

export function QcOverrideDialog({
  stageId,
  open,
  onOpenChange,
  pending,
  pendingItems,
  onChanged,
  advisory = false,
  onDone,
}: QcOverrideDialogProps) {
  const [reason, setReason] = useState<QcOverrideReason | null>(null);
  const [note, setNote] = useState("");
  /** Indeksy rzeczy oznaczonych „QC się myli”. */
  const [wrong, setWrong] = useState<ReadonlySet<number>>(new Set());
  /** Indeksy rzeczy, których dotyczy „Inny powód” (R6). */
  const [about, setAbout] = useState<ReadonlySet<number>>(new Set());
  const [touched, setTouched] = useState(false);
  const { showSuccess, showError } = useToast();
  const override = useQcOverride(stageId, onChanged);
  const noteId = useId();
  const errorId = useId();

  const items: readonly QcPendingItem[] =
    pendingItems ?? pending.map((title) => ({ title, keys: [], labelable: false }));
  const aboutChoices = items.map((item, index) => ({ item, index })).filter(({ item }) => item.keys.length > 0);
  const pointsAtItem = reason !== null && QC_OVERRIDE_POINTS_AT_ITEM.has(reason);
  const error = qcOverrideError(reason, note, { required: aboutChoices.length > 0, picked: about.size });
  const close = (next: boolean) => {
    if (!next) {
      setReason(null);
      setNote("");
      setTouched(false);
      setWrong(new Set());
      setAbout(new Set());
    }
    onOpenChange(next);
  };
  const submit = () => {
    setTouched(true);
    if (error || !reason || override.isPending) return;
    const clean = note.trim();
    const wrongKeys = (pendingItems ?? []).flatMap((item, index) => (wrong.has(index) ? item.keys : []));
    const aboutKeys = pointsAtItem ? items.flatMap((item, index) => (about.has(index) ? item.keys : [])) : [];
    override.mutate(
      {
        reason_code: reason,
        ...(clean ? { reason: clean } : {}),
        ...(wrongKeys.length > 0 ? { wrong_keys: wrongKeys } : {}),
        ...(aboutKeys.length > 0 ? { about_keys: aboutKeys } : {}),
      },
      {
      onSuccess: (result) => {
        showSuccess("Przepuszczono mimo QC — powód zapisany w historii.");
        close(false);
        onDone?.(result);
      },
      onError: (err) => showError(apiErrorMessage(err, "Nie udało się przepuścić. Spróbuj ponownie.")),
      },
    );
  };
  const rest = items.length - PENDING_SHOWN;
  const labelable = items.slice(0, PENDING_SHOWN).some((item) => item.labelable);
  const toggleAbout = (index: number) =>
    setAbout((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  const toggle = (index: number, isWrong: boolean) =>
    setWrong((current) => {
      const next = new Set(current);
      if (isWrong) next.add(index);
      else next.delete(index);
      return next;
    });

  return (
    <AppModal
      open={open}
      onOpenChange={close}
      size="md"
      title={advisory ? "Przesuń mimo uwag QC" : "Przepuść mimo QC"}
      description={
        advisory
          ? "Delivery Lead dostanie powiadomienie, zobaczy, co zostało niepoprawione, i może cofnąć kartę do poprawy."
          : "Powód zobaczy każdy w historii kandydata."
      }
      footer={
        <>
          <Button variant="outline" onClick={() => close(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={override.isPending || (touched && !!error)}>
            {override.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
            {advisory ? "Przesuń mimo uwag" : "Przepuść CV"}
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
          <p>{overrideSummary(items.length)}</p>
          {items.length > 0 ? (
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {items.slice(0, PENDING_SHOWN).map((item, i) => (
                <li key={i}>
                  <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                    <span className="min-w-0">{item.title}</span>
                    {item.labelable ? (
                      <span role="group" aria-label={`Czy QC ma rację: ${item.title}`} className="flex flex-none gap-1">
                        {[false, true].map((isWrong) => (
                          <button
                            key={String(isWrong)}
                            type="button"
                            aria-pressed={wrong.has(i) === isWrong}
                            onClick={() => toggle(i, isWrong)}
                            className={cn(
                              "rounded border px-1.5 py-0.5 text-xs",
                              wrong.has(i) === isWrong
                                ? "border-foreground bg-foreground text-background"
                                : "border-border bg-background text-foreground",
                            )}
                          >
                            {isWrong ? "QC się myli" : "Prawda"}
                          </button>
                        ))}
                      </span>
                    ) : null}
                  </span>
                </li>
              ))}
              {rest > 0 ? <li>i {countForm(rest, ["inna", "inne", "innych"])}</li> : null}
            </ul>
          ) : null}
          {labelable ? (
            <p className="mt-1.5 text-xs">„QC się myli” liczy się do trafności w „Jakość QC” — reszta to „prawda, ale przepuszczam”.</p>
          ) : null}
        </div>
        <RadioGroup
          value={reason ?? ""}
          onValueChange={(value) => setReason(value as QcOverrideReason)}
          aria-label="Dlaczego przepuszczasz?"
          aria-describedby={touched && error ? errorId : undefined}
        >
          {QC_OVERRIDE_REASONS.map(({ code, label }) => {
            const id = `${noteId}-${code}`;
            return (
              <label key={code} htmlFor={id} className="flex cursor-pointer items-center gap-2 text-sm">
                <RadioGroupItem id={id} value={code} />
                {code === "other" ? `${label} — napiszę niżej` : label}
              </label>
            );
          })}
        </RadioGroup>
        <div className="space-y-1">
          <label htmlFor={noteId} className="text-xs font-medium text-muted-foreground">
            {reason === "other"
              ? "Szczegóły (wymagane)"
              : reason === "confirmed_in_call"
                ? "Co dokładnie powiedział kandydat? (wymagane)"
                : "Szczegóły (nie musisz nic wpisywać)"}
          </label>
          <Textarea
            id={noteId}
            rows={2}
            value={note}
            maxLength={QC_OVERRIDE_NOTE_MAX}
            invalid={touched && (reason === "other" || reason === "confirmed_in_call") && !!error}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
        {pointsAtItem && aboutChoices.length > 0 ? (
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-medium text-muted-foreground">Której uwagi dotyczy powód?</legend>
            <div className="space-y-1">
              {aboutChoices.map(({ item, index }) => {
                const id = `${noteId}-about-${index}`;
                return (
                  <label key={index} htmlFor={id} className="flex cursor-pointer items-start gap-2 text-sm">
                    <input
                      id={id}
                      type="checkbox"
                      className="mt-0.5 size-4 accent-primary"
                      checked={about.has(index)}
                      onChange={() => toggleAbout(index)}
                    />
                    <span className="min-w-0">{item.title}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        ) : null}
        {reason === "confirmed_in_call" ? (
          // D3 (17.10.2026): notatki pary czytają QC, generator CV i AI — rekruter ma wiedzieć, że powstaną.
          <p className="text-xs text-muted-foreground">
            Przy rzeczach, których nie ma w oryginale ani w notatkach, zapiszemy w notatkach kandydata „Potwierdzone z
            kandydatem” z tym zdaniem, a zobaczy je też Delivery Lead. Czytają je QC i generator CV — kolejne CV tej osoby nie będzie już tego
            zgłaszać.
          </p>
        ) : null}
        {touched && error ? (
          <p id={errorId} role="alert" className="text-xs text-destructive">
            {error}
          </p>
        ) : null}
      </form>
    </AppModal>
  );
}

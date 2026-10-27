"use client";

/**
 * Przypomnienia o brakujących ogłoszeniach w oknie „Ogłoszenie” (27.10.2026).
 *
 * Codziennie rano mail mówi osobie, który kanał rekrutacji (strona kariery,
 * Pracuj.pl, JustJoin.IT) ma wstawić. Tu widać, kto robi brakujący kanał,
 * a Delivery Lead rekrutacji (także Head of Recruitment i admin) może zapisać
 * „Nie publikujemy tu” z powodem albo przypomnieć rekruterowi o stronie
 * kariery. Serwer pilnuje tego samego (`job_ad.reminders.can_manage`).
 * Reguły: `docs/claude/rekrutacja-tworzenie/ogloszenia-przypomnienia-mailem.md`.
 */

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  AD_CHANNEL_LABEL,
  type AdChannel,
  type AdChannelView,
} from "@/lib/api/jobAd";
import { formatDate } from "@/lib/utils";

export const SKIP_REASON_MIN = 3;
export const SKIP_REASON_MAX = 300;

/** „Julia Sowa” → „Julia S.” — jak w mailu. */
export function shortName(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

export function ownersText(view: AdChannelView): string {
  return view.owner_names.map(shortName).filter(Boolean).join(", ");
}

/** Jedna linia pod kanałem: kto robi brak albo zapisane „nie publikujemy”. */
export function ChannelReminderLine({
  view,
  canManage,
  busy,
  onSkip,
  onUnskip,
}: {
  view: AdChannelView;
  canManage: boolean;
  busy: boolean;
  onSkip: () => void;
  onUnskip: () => void;
}) {
  if (view.state === "skipped") {
    const who = [view.skipped_by_name ? shortName(view.skipped_by_name) : null, view.since ? formatDate(view.since) : null]
      .filter(Boolean)
      .join(", ");
    return (
      <div
        data-testid={`ad-channel-skipped-${view.channel}`}
        className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md bg-muted px-2.5 py-1.5 text-xs text-muted-foreground"
      >
        <span>
          Nie publikujemy: <span className="text-foreground">{view.skip_reason}</span>
          {who ? ` (${who})` : ""}
        </span>
        {canManage ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="ml-auto h-6 px-2"
            disabled={busy}
            onClick={onUnskip}
          >
            Cofnij
          </Button>
        ) : null}
      </div>
    );
  }
  if (view.state !== "missing") return null;
  const owners = ownersText(view);
  return (
    <div
      data-testid={`ad-channel-missing-${view.channel}`}
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"
    >
      <span>
        {view.mine
          ? "Przypomnienie przychodzi do Ciebie codziennie rano."
          : owners
            ? `Robi: ${owners} — dostaje przypomnienie codziennie rano.`
            : "Nikt jeszcze tego nie robi."}
      </span>
      {canManage ? (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="ml-auto h-6 px-2"
          disabled={busy}
          onClick={onSkip}
        >
          Nie publikujemy tu
        </Button>
      ) : null}
    </div>
  );
}

export interface SkipChannelDialogProps {
  open: boolean;
  /** Kanały do wyboru (brakujące). */
  channels: readonly AdChannel[];
  /** Zaznaczone na start. */
  initial: readonly AdChannel[];
  saving: boolean;
  onSubmit: (channels: AdChannel[], reason: string) => void;
  onClose: () => void;
}

/** „Nie publikujemy tej rekrutacji na …” — kanały i powód (obowiązkowy). */
export function SkipChannelDialog({
  open,
  channels,
  initial,
  saving,
  onSubmit,
  onClose,
}: SkipChannelDialogProps) {
  const [picked, setPicked] = useState<AdChannel[]>([...initial]);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) {
      setPicked([...initial]);
      setReason("");
    }
    // Stan zeruje się przy każdym otwarciu okna.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const cleanReason = reason.trim();
  const valid = picked.length > 0 && cleanReason.length >= SKIP_REASON_MIN;

  return (
    <Dialog open={open} onOpenChange={(value) => (value ? undefined : onClose())}>
      <DialogContent size="md" data-testid="ad-skip-dialog">
        <DialogHeader>
          <DialogTitle>Nie publikujemy tej rekrutacji</DialogTitle>
          <DialogDescription>
            Przypomnienia o zaznaczonych kanałach przestaną przychodzić. Powód zobaczy
            zespół rekrutacji i Historia zdarzeń.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-[13px] font-medium text-foreground">Gdzie</legend>
            {channels.map((channel) => (
              <label key={channel} className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={picked.includes(channel)}
                  onCheckedChange={(value) =>
                    setPicked((prev) =>
                      value === true
                        ? [...prev.filter((c) => c !== channel), channel]
                        : prev.filter((c) => c !== channel),
                    )
                  }
                  aria-label={AD_CHANNEL_LABEL[channel]}
                />
                {AD_CHANNEL_LABEL[channel]}
              </label>
            ))}
          </fieldset>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-foreground">Dlaczego</span>
            <Textarea
              value={reason}
              maxLength={SKIP_REASON_MAX}
              rows={3}
              placeholder="Np. klient nie zgadza się na ogłoszenia z nazwą projektu"
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
            Anuluj
          </Button>
          <Button
            type="button"
            loading={saving}
            disabled={!valid}
            title={valid ? undefined : "Zaznacz kanał i napisz krótko, dlaczego."}
            onClick={() => onSubmit(picked, cleanReason)}
          >
            Zapisz „nie publikujemy”
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

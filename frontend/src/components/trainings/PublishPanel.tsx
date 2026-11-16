"use client";

import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type { TrainingView, TrainingsMe } from "@/lib/api/trainings";
import { formatDateTimePl } from "@/lib/date-pl";

import { paymentBlockReason, publishBlockReason } from "./training-model";

interface PublishPanelProps {
  view: Pick<
    TrainingView,
    "status" | "trainer_kind" | "payment" | "files" | "can_publish" | "published_at"
  >;
  me: Pick<TrainingsMe, "can_manage" | "can_pay">;
  onPaid: (paid: boolean) => Promise<boolean>;
  onPublish: (publish: boolean) => Promise<boolean>;
  busy?: boolean;
}

/** Zapłata (Finanse) i publikacja w bibliotece (TCM, po zapłacie, druga osoba). */
export function PublishPanel({ view, me, onPaid, onPublish, busy }: PublishPanelProps) {
  const { askConfirm, confirmDialog } = useConfirmV2();
  const consultant = view.trainer_kind === "consultant";
  const paymentBlock = paymentBlockReason(view, me);
  const publishBlock = publishBlockReason(view, me);

  return (
    <div className="space-y-4">
      {confirmDialog}
      {consultant ? (
        <section className="space-y-1.5" aria-label="Zapłata">
          <p className="text-sm">
            {view.payment.paid_at ? (
              <>Zapłacone {formatDateTimePl(view.payment.paid_at)}.</>
            ) : view.payment.invoice_ready_at ? (
              <>
                Wszystkie pliki przyjęte {formatDateTimePl(view.payment.invoice_ready_at)}. Trener
                może wystawić fakturę, termin płatności 14 dni.
              </>
            ) : (
              <>Faktura po przyjęciu wszystkich wymaganych plików.</>
            )}
          </p>
          {me.can_pay ? (
            view.payment.paid_at ? (
              <Button
                size="sm"
                variant="outline"
                disabled={busy || Boolean(view.published_at)}
                title={view.published_at ? "Najpierw wycofaj szkolenie z biblioteki." : undefined}
                onClick={async () => {
                  const ok = await askConfirm({
                    title: "Cofnąć oznaczenie zapłaty?",
                    description: "Szkolenie nie będzie mogło wejść do biblioteki, dopóki Finanse znów nie oznaczą zapłaty.",
                    confirmLabel: "Cofnij zapłatę",
                    variant: "destructive",
                  });
                  if (ok) await onPaid(false);
                }}
              >
                Cofnij „Zapłacone”
              </Button>
            ) : (
              <div className="space-y-1">
                <Button size="sm" disabled={busy || paymentBlock !== null} onClick={() => onPaid(true)}>
                  Zapłacone
                </Button>
                {paymentBlock ? (
                  <p className="text-xs text-muted-foreground">{paymentBlock}</p>
                ) : null}
              </div>
            )
          ) : null}
        </section>
      ) : null}

      <section className="space-y-1.5" aria-label="Biblioteka">
        {view.published_at ? (
          <>
            <p className="text-sm">W bibliotece od {formatDateTimePl(view.published_at)}.</p>
            {me.can_manage ? (
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={async () => {
                  const ok = await askConfirm({
                    title: "Wycofać szkolenie z biblioteki?",
                    description: "Nagranie i materiały znikną z biblioteki dla wszystkich.",
                    confirmLabel: "Wycofaj",
                    variant: "destructive",
                  });
                  if (ok) await onPublish(false);
                }}
              >
                Wycofaj z biblioteki
              </Button>
            ) : null}
          </>
        ) : me.can_manage ? (
          <div className="space-y-1">
            <Button
              size="sm"
              disabled={busy || publishBlock !== null}
              onClick={async () => {
                const ok = await askConfirm({
                  title: "Opublikować w bibliotece?",
                  description:
                    "Pliki zaznaczone „Dla uczestników” zobaczą wszyscy w NEXUSIE i konsultanci w panelu. Nagranie zatwierdza osoba, która go nie wgrała.",
                  confirmLabel: "Opublikuj",
                });
                if (ok) await onPublish(true);
              }}
            >
              Opublikuj w bibliotece
            </Button>
            {publishBlock ? (
              <p className="text-xs text-muted-foreground" data-testid="publish-block">
                {publishBlock}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Jeszcze nie ma go w bibliotece.</p>
        )}
      </section>
    </div>
  );
}

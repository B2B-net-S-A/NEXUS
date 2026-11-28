"use client";

import { useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCandidateReferrals,
  useMarkReferralPaid,
  useUpdateReferral,
  type CandidateReferral,
  type ReferralChange,
  type ReferralStatus,
} from "@/lib/api/candidateReferrals";
import { formatDateTimePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { safeExternalHref } from "@/lib/safe-href";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

import {
  BONUS_MAX,
  BONUS_MIN,
  REFERRAL_STATUSES,
  REFERRAL_STATUS_LABEL,
  actionsFor,
  formatBonus,
  parseBonus,
  payoutLine,
  type ReferralAction,
} from "./referral-model";

const TONES: Record<ReferralStatus, "info" | "warning" | "success" | "neutral"> = {
  new: "info",
  contacted: "warning",
  started: "success",
  paid: "neutral",
  rejected: "neutral",
};

function Contact({ referral }: { referral: CandidateReferral }) {
  if (referral.referred_email) return <span className="break-all">{referral.referred_email}</span>;
  const href = safeExternalHref(referral.referred_linkedin);
  if (!href) return <span className="text-muted-foreground">brak kontaktu</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">
      Profil LinkedIn
    </a>
  );
}

/** Zakładka „Polecenia” kolejki zgłoszeń: polecenia ze strony i premia za nie. */
export function ReferralsPanel() {
  const user = useAuthStore((state) => state.user);
  const canPay = hasPermission(user, "finance_module");
  const referrals = useCandidateReferrals();
  const update = useUpdateReferral();
  const markPaid = useMarkReferralPaid();
  const { showSuccess, showError } = useToast();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const [filter, setFilter] = useState<ReferralStatus>("new");
  const busy = update.isPending || markPaid.isPending;

  const all = referrals.data ?? [];
  const shown = all.filter((referral) => referral.status === filter);

  const change = async (referral: CandidateReferral, body: ReferralChange, done: string) => {
    try {
      await update.mutateAsync({ id: referral.id, change: body });
      showSuccess(done);
    } catch (error: unknown) {
      showError(apiErrorMessage(error, "Nie udało się zapisać polecenia."));
    }
  };

  const askBonus = async (referral: CandidateReferral, title: string): Promise<string | null> => {
    const raw = await askReason({
      title,
      description: `${referral.referred_name}. Premia od ${BONUS_MIN} do ${BONUS_MAX} zł, zależnie od profilu.`,
      confirmLabel: "Zapisz",
      field: { label: "Kwota premii (zł)", placeholder: "np. 2500", minLength: 4, maxLength: 12 },
    });
    if (raw === null) return null;
    const amount = parseBonus(raw);
    if (amount === null) {
      showError(`Premia za polecenie to od ${BONUS_MIN} do ${BONUS_MAX} zł.`);
      return null;
    }
    return amount;
  };

  const run = async (referral: CandidateReferral, action: ReferralAction) => {
    if (action.kind === "paid") {
      const confirmed = await askConfirm({
        title: "Oznaczyć premię jako wypłaconą?",
        description: `${formatBonus(referral.bonus_amount)} dla: ${referral.referrer_name}. Polecenie zostanie zamknięte.`,
        confirmLabel: "Wypłacona",
      });
      if (!confirmed) return;
      try {
        await markPaid.mutateAsync(referral.id);
        showSuccess("Premia oznaczona jako wypłacona.");
      } catch (error: unknown) {
        showError(apiErrorMessage(error, "Nie udało się oznaczyć wypłaty."));
      }
      return;
    }
    if (action.kind === "bonus") {
      const amount = await askBonus(referral, "Zmienić kwotę premii?");
      if (amount !== null) await change(referral, { bonus_amount: amount }, "Kwota premii zapisana.");
      return;
    }
    if (!action.to) return;
    if (action.to === "started") {
      const amount = referral.bonus_amount ?? (await askBonus(referral, "Polecona osoba zaczęła projekt?"));
      if (amount === null) return;
      await change(
        referral,
        { status: "started", bonus_amount: amount },
        "Premia należna. Wypłatę oznaczą Finanse.",
      );
      return;
    }
    const note = await askReason({
      title: `${action.label}: ${referral.referred_name}?`,
      description: "Notatka zostaje przy poleceniu (opcjonalnie).",
      confirmLabel: action.label,
      variant: action.destructive ? "destructive" : "default",
      field: {
        label: "Notatka",
        placeholder: "np. termin rozmowy albo powód",
        minLength: 0,
        maxLength: 1000,
      },
    });
    if (note === null) return;
    await change(
      referral,
      { status: action.to, ...(note ? { note } : {}) },
      `Polecenie: ${REFERRAL_STATUS_LABEL[action.to].toLowerCase()}.`,
    );
  };

  if (referrals.isLoading) {
    return <p className="text-sm text-muted-foreground">Wczytywanie poleceń…</p>;
  }
  if (referrals.isError) {
    return (
      <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
        {apiErrorMessage(referrals.error, "Nie udało się pobrać poleceń.")}
      </p>
    );
  }

  return (
    <section aria-labelledby="referrals-title" className="space-y-3">
      {confirmDialog}
      <div>
        <h2 id="referrals-title" className="text-base font-semibold text-foreground">
          Polecenia ze strony
        </h2>
        <p className="text-sm text-muted-foreground">
          „Poleć inżyniera” na b2bnetwork.pl. Polecona osoba nie dostała od nas żadnego maila:
          zadzwoń do niej, a gdy zacznie projekt, wpisz premię ({BONUS_MIN}–{BONUS_MAX} zł).
        </p>
      </div>
      <div role="group" aria-label="Filtr statusu" className="flex flex-wrap gap-1.5">
        {REFERRAL_STATUSES.map((status) => (
          <button
            key={status}
            type="button"
            aria-pressed={filter === status}
            onClick={() => setFilter(status)}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium",
              filter === status
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {REFERRAL_STATUS_LABEL[status]}
            <span className="tabular-nums">
              {all.filter((referral) => referral.status === status).length}
            </span>
          </button>
        ))}
      </div>
      {referrals.isSuccess && shown.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-border bg-muted/40 p-8 text-center text-sm text-muted-foreground">
          Nic w tym stanie.
        </p>
      ) : (
        <ul className="space-y-3">
          {shown.map((referral) => (
            <li key={referral.id} className="rounded-2xl border border-border bg-card p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-base font-semibold text-foreground">{referral.referred_name}</p>
                  <p className="text-sm text-muted-foreground">
                    <Contact referral={referral} />
                    {referral.referred_role ? ` · ${referral.referred_role}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {referral.was_in_database ? <Badge variant="neutral">był już w bazie</Badge> : null}
                  <Badge variant={TONES[referral.status]}>{REFERRAL_STATUS_LABEL[referral.status]}</Badge>
                </div>
              </div>
              <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted-foreground">Polecił(a)</dt>
                  <dd className="break-all">
                    {referral.referrer_name} ({referral.referrer_email})
                  </dd>
                  <dd className="text-xs text-muted-foreground">{payoutLine(referral)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Premia</dt>
                  <dd>{formatBonus(referral.bonus_amount)}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-xs text-muted-foreground">Oświadczenie polecającego</dt>
                  <dd className="text-muted-foreground">„{referral.statement_text}”</dd>
                </div>
                {referral.status_note ? (
                  <div className="sm:col-span-2">
                    <dt className="text-xs text-muted-foreground">Notatka</dt>
                    <dd className="whitespace-pre-line">{referral.status_note}</dd>
                  </div>
                ) : null}
              </dl>
              <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                <span>polecenie {formatDateTimePl(referral.created_at)}</span>
                {referral.candidate_id !== null ? (
                  <Link
                    href={`/candidates/${referral.candidate_id}`}
                    className="font-medium text-primary hover:underline"
                  >
                    profil kandydata #{referral.candidate_id}
                  </Link>
                ) : (
                  <span>bez profilu (adres usunięty wcześniej na prośbę osoby)</span>
                )}
              </div>
              {actionsFor(referral, { canPay }).length > 0 ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {actionsFor(referral, { canPay }).map((action) => (
                    <Button
                      key={`${action.kind}-${action.to ?? ""}`}
                      type="button"
                      size="sm"
                      variant={action.destructive ? "outline" : "primary"}
                      disabled={busy}
                      onClick={() => void run(referral, action)}
                    >
                      {action.label}
                    </Button>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

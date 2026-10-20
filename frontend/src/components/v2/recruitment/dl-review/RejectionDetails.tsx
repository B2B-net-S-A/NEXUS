/**
 * Uzasadnienie odrzucenia w przeglądzie DL (20.10.2026).
 *
 * Delivery Lead odrzucał osobę, bo była już na rozmowie u managera tej
 * rekrutacji, i nie miał gdzie tego napisać: przy „Inne” w historii zostawało
 * samo słowo. Teraz:
 * - `RejectionDetails` — opis powodu (przy „Inne” obowiązkowy), a przy
 *   „Już po rozmowie u tego hiring managera” wybór rozmowy z listy;
 * - `SameManagerNotice` — ostrzeżenie, gdy osoba była na rozmowie u TEGO
 *   SAMEGO hiring managera w innej rekrutacji (nie blokuje akceptacji).
 *
 * Opis jedzie jako `notes` ruchu — profil kandydata pokazuje „Powód — opis”.
 */

import Link from "next/link";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { DlReviewEarlierInterview } from "@/lib/api/dlReview";
import { formatDate } from "@/lib/utils";

/** Wartość radia „Poza NEXUSEM / nie ma na liście”. */
export const OUTSIDE_NEXUS = "outside";
const DESCRIPTION_MAX = 1000;

export interface RejectionDetailsValue {
  description: string;
  /** `job_id` wybranej rozmowy, `OUTSIDE_NEXUS` albo "" (nic). */
  interviewJobId: string;
}

export const EMPTY_REJECTION_DETAILS: RejectionDetailsValue = {
  description: "",
  interviewJobId: "",
};

function interviewLine(item: DlReviewEarlierInterview): string {
  return `${item.job_title} · rozmowa ${formatDate(item.interview_at)}`;
}

/** Notatka ruchu z opisu i wybranej rozmowy; "" = nic do zapisania. */
export function rejectionNotes(
  value: RejectionDetailsValue,
  { hmReason, interviews }: { hmReason: boolean; interviews: readonly DlReviewEarlierInterview[] },
): string {
  const description = value.description.trim();
  const picked = hmReason
    ? interviews.find((item) => String(item.job_id) === value.interviewJobId)
    : undefined;
  if (!picked) return description;
  return description ? `${interviewLine(picked)} — ${description}` : interviewLine(picked);
}

/** Czy uzasadnienie pozwala potwierdzić odrzucenie. */
export function rejectionDetailsReady(
  value: RejectionDetailsValue,
  opts: { required: boolean; hmReason: boolean; interviews: readonly DlReviewEarlierInterview[] },
): boolean {
  if (!opts.required) return true;
  if (opts.hmReason && opts.interviews.length > 0 && value.interviewJobId === "") return false;
  return rejectionNotes(value, opts) !== "";
}

interface RejectionDetailsProps {
  required: boolean;
  hmReason: boolean;
  interviews: readonly DlReviewEarlierInterview[];
  value: RejectionDetailsValue;
  onChange: (value: RejectionDetailsValue) => void;
}

export function RejectionDetails({
  required,
  hmReason,
  interviews,
  value,
  onChange,
}: RejectionDetailsProps) {
  const listed = hmReason && interviews.length > 0;
  // Przy rozmowie z listy opis jest dopiskiem; poza listą — jedynym śladem.
  const descriptionRequired =
    required && (!listed || value.interviewJobId === OUTSIDE_NEXUS);
  const label = hmReason
    ? listed
      ? descriptionRequired
        ? "Na jakiej rozmowie i kiedy? *"
        : "Dopisek (opcjonalnie)"
      : "Na jakiej rozmowie i kiedy? *"
    : required
      ? "Opisz powód *"
      : "Opis powodu (opcjonalnie)";

  return (
    <div className="space-y-2">
      {listed ? (
        <fieldset className="space-y-1.5" data-testid="dl-reject-interviews">
          <legend className="mb-1 text-xs font-medium">Na której rozmowie? *</legend>
          {interviews.map((item) => {
            const id = String(item.job_id);
            return (
              <label
                key={id}
                className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-2 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5"
              >
                <input
                  type="radio"
                  name="dl-reject-interview"
                  className="mt-0.5 size-4 shrink-0"
                  checked={value.interviewJobId === id}
                  onChange={() => onChange({ ...value, interviewJobId: id })}
                />
                <span className="min-w-0 [overflow-wrap:anywhere]">
                  <span className="font-medium">{item.job_title}</span>
                  <span className="block text-xs text-muted-foreground">
                    {formatDate(item.interview_at)}
                    {item.latest_stage ? ` · ${item.latest_stage}` : ""}
                    {item.same_hiring_manager ? " · ten sam hiring manager" : ""}
                  </span>
                </span>
              </label>
            );
          })}
          <label className="flex cursor-pointer items-center gap-2 rounded-md border border-border p-2 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5">
            <input
              type="radio"
              name="dl-reject-interview"
              className="size-4 shrink-0"
              checked={value.interviewJobId === OUTSIDE_NEXUS}
              onChange={() => onChange({ ...value, interviewJobId: OUTSIDE_NEXUS })}
            />
            Poza NEXUSEM / nie ma na liście
          </label>
        </fieldset>
      ) : null}
      <label className="block text-xs font-medium">
        {label}
        <textarea
          className="mt-1 block min-h-9 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm font-normal"
          rows={2}
          maxLength={DESCRIPTION_MAX}
          value={value.description}
          placeholder={
            hmReason
              ? "Np. Rating & Limit Management, rozmowa 21.08 — manager nie chce jej drugi raz."
              : undefined
          }
          onChange={(e) => onChange({ ...value, description: e.target.value })}
        />
        <span className="mt-1 block text-[11px] font-normal text-muted-foreground">
          Zostaje w historii kandydata obok powodu. Nie trafia do maila.
        </span>
      </label>
    </div>
  );
}

interface SameManagerNoticeProps {
  interviews: readonly DlReviewEarlierInterview[];
  managerName: string | null | undefined;
  canReject: boolean;
  onReject: () => void;
  onDismiss: () => void;
}

export function SameManagerNotice({
  interviews,
  managerName,
  canReject,
  onReject,
  onDismiss,
}: SameManagerNoticeProps) {
  const same = interviews.filter((item) => item.same_hiring_manager);
  if (same.length === 0) return null;
  return (
    <div
      role="note"
      data-testid="dl-review-same-manager"
      className="space-y-2 rounded-lg bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
    >
      <p className="flex items-start gap-2 font-semibold">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1">
          Ta osoba była już na rozmowie u hiring managera tej rekrutacji
          {managerName ? ` (${managerName})` : ""}.
        </span>
      </p>
      <ul className="space-y-1 pl-6">
        {same.map((item) => (
          <li key={item.job_id} className="[overflow-wrap:anywhere]">
            <Link href={`/jobs/${item.job_id}`} className="font-medium underline-offset-2 hover:underline">
              {item.job_title}
            </Link>{" "}
            · {formatDate(item.interview_at)}
            {item.latest_stage ? ` · ${item.latest_stage}` : ""}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2 pl-6">
        {canReject ? (
          <Button size="sm" variant="destructive" onClick={onReject}>
            Odrzuć z tym powodem
          </Button>
        ) : null}
        <Button size="sm" variant="outline" onClick={onDismiss}>
          Wiem — oceniam dalej
        </Button>
      </div>
    </div>
  );
}

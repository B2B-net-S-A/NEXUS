"use client";

/**
 * Mail odrzucenia w oknie odrzucenia — checkbox i podgląd (13.10.2026).
 *
 * Decyzje Artura D1–D6: okno pokazuje adresata, temat i treść, zanim ktoś
 * potwierdzi. Przy jednej osobie temat i treść da się poprawić (wysyłamy
 * dokładnie ten tekst, serwer robi escape), przy kilku podgląd jest tylko do
 * odczytu z listą, kto dostanie mail. Brak skrzynki, adresu albo uprawnień
 * widać od razu — checkbox jest wtedy wyłączony.
 *
 * Podgląd: `POST /api/rejection-emails/preview` (ta sama reguła co planowanie
 * wysyłki w `rejection_email_scheduler`).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mail, PenLine } from "lucide-react";

import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  rejectionEmailBlockedMessage,
  rejectionEmailPreviewKey,
  rejectionEmailSkipShort,
  type RejectionEmailPreview,
  type RejectionEmailText,
} from "@/lib/rejection-email";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export interface RejectionEmailPeople {
  jobId: number;
  people: { candidateId: number; name: string }[];
}

/** Co okno odrzucenia musi wiedzieć przy „Potwierdź”. */
export interface RejectionEmailFieldState {
  /** Mail nie wyjdzie do nikogo — checkbox wyłączony. */
  blocked: boolean;
  /** Zaznaczony mail z pustym tematem albo treścią — „Potwierdź” czeka. */
  invalid: boolean;
  /** Poprawiony temat i treść (jedna osoba); `null` = treść domyślna. */
  text: RejectionEmailText | null;
}

interface Props {
  /** `null` — wołający nie podał rekrutacji i osób: sam checkbox, bez podglądu. */
  preview: RejectionEmailPeople | null;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  onStateChange: (state: RejectionEmailFieldState) => void;
}

export function RejectionEmailField({
  preview,
  checked,
  onCheckedChange,
  onStateChange,
}: Props) {
  const ids = useMemo(
    () => (preview?.people ?? []).map((p) => p.candidateId),
    [preview]
  );
  const single = ids.length === 1;
  const query = useQuery({
    queryKey: rejectionEmailPreviewKey(preview?.jobId ?? 0, ids),
    queryFn: () =>
      api
        .post<RejectionEmailPreview>("/api/rejection-emails/preview", {
          job_id: preview?.jobId,
          candidate_ids: ids,
        })
        .then((r) => r.data),
    enabled: preview !== null && ids.length > 0,
    staleTime: 0,
    // Awaria podglądu nie blokuje odrzucenia (mail wyjdzie z treścią
    // domyślną) — od razu to mówimy, zamiast ponawiać w tle.
    retry: false,
  });
  const data = query.isSuccess ? query.data : null;

  const people = data?.people ?? [];
  const eligible = people.filter((p) => !p.skip_reason);
  const blockedMessage = (() => {
    if (!data || eligible.length > 0) return null;
    const reasons = new Set(people.map((p) => p.skip_reason ?? ""));
    if (reasons.size === 1) return rejectionEmailBlockedMessage([...reasons][0]);
    return "Mail nie wyjdzie do nikogo z zaznaczonych osób.";
  })();
  const blocked = blockedMessage !== null;

  const defaults: RejectionEmailText | null =
    data?.subject != null && data?.body != null
      ? { subject: data.subject, body: data.body }
      : null;
  const [draft, setDraft] = useState<RejectionEmailText | null>(null);
  useEffect(() => {
    if (defaults && draft === null) setDraft(defaults);
    // Szkic startuje z treści domyślnej raz — kolejne odświeżenia zapytania
    // nie nadpisują tego, co ktoś już poprawił.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults?.subject, defaults?.body]);

  const editDraft = single && defaults !== null ? draft : null;
  const edited =
    editDraft !== null &&
    defaults !== null &&
    (editDraft.subject !== defaults.subject || editDraft.body !== defaults.body);
  const subjectEmpty = editDraft !== null && editDraft.subject.trim() === "";
  const bodyEmpty = editDraft !== null && editDraft.body.trim() === "";
  const invalid = checked && (subjectEmpty || bodyEmpty);

  useEffect(() => {
    if (blocked && checked) onCheckedChange(false);
  }, [blocked, checked, onCheckedChange]);

  useEffect(() => {
    onStateChange({
      blocked,
      invalid,
      text: edited && editDraft ? { subject: editDraft.subject, body: editDraft.body } : null,
    });
  }, [blocked, invalid, edited, editDraft, onStateChange]);

  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (checked) boxRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [checked, data]);

  const label = single || preview === null
    ? "Powiadomienie e-mail do kandydata"
    : "Powiadomienie e-mail do kandydatów";
  const firstName =
    preview?.people.find((p) => p.candidateId === eligible[0]?.candidate_id)?.name ?? null;

  return (
    <FormField label={label}>
      <label
        className={`flex items-start gap-2 text-sm rounded-md p-1.5 ${
          blocked ? "text-muted-foreground" : "cursor-pointer hover:bg-primary/10"
        }`}
      >
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))] text-primary focus:ring-primary"
          checked={checked && !blocked}
          disabled={blocked}
          onChange={(e) => onCheckedChange(e.target.checked)}
        />
        <span className="flex items-start gap-1.5">
          <Mail className="mt-0.5 h-3.5 w-3.5 text-[hsl(var(--muted-foreground))] shrink-0" />
          <span>
            {single || preview === null
              ? "Wyślij e-mail do kandydata 15 minut po potwierdzeniu."
              : "Wyślij e-mail 15 minut po potwierdzeniu."}{" "}
            Do tego czasu można cofnąć wysyłkę.
          </span>
        </span>
      </label>

      {blockedMessage ? (
        <Alert variant="warning" description={blockedMessage} className="mt-1 py-2" />
      ) : null}

      {checked && !blocked && preview !== null ? (
        <div ref={boxRef} className="mt-1" data-testid="rejection-email-preview">
          {query.isPending ? (
            <p className="px-1.5 text-xs text-muted-foreground">Wczytuję podgląd maila…</p>
          ) : query.isError ? (
            <Alert
              variant="error"
              className="py-2"
              description={`${apiErrorMessage(
                query.error,
                "Nie udało się wczytać podglądu maila."
              )} Mail wyjdzie z treścią domyślną.`}
            />
          ) : editDraft && defaults ? (
            <div className="rounded-lg border border-primary/30">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-t-lg border-b border-border bg-primary/5 px-3 py-1.5">
                <span className="text-xs font-semibold uppercase tracking-[0.06em] text-primary">
                  Podgląd maila
                </span>
                {edited ? (
                  <span className="flex items-center gap-2">
                    <Badge variant="warning" size="sm">
                      Zmieniona ręcznie
                    </Badge>
                    <button
                      type="button"
                      className="text-xs font-medium text-primary hover:underline"
                      onClick={() => setDraft(defaults)}
                    >
                      Przywróć treść domyślną
                    </button>
                  </span>
                ) : null}
              </div>
              <div className="space-y-2 p-3">
                <p className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2 text-sm">
                  <span className="text-xs text-muted-foreground">Do</span>
                  <span className="break-all">{people[0]?.to_email}</span>
                </p>
                <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-2">
                  <label
                    htmlFor="rejection-email-subject"
                    className="text-xs text-muted-foreground"
                  >
                    Temat
                  </label>
                  <Input
                    id="rejection-email-subject"
                    className="h-9"
                    value={editDraft.subject}
                    maxLength={998}
                    invalid={subjectEmpty}
                    onChange={(e) => setDraft({ ...editDraft, subject: e.target.value })}
                  />
                </div>
                {subjectEmpty ? (
                  <p className="text-xs text-destructive">Temat maila nie może być pusty.</p>
                ) : null}
                <div className="space-y-1">
                  <label
                    htmlFor="rejection-email-body"
                    className="text-xs text-muted-foreground"
                  >
                    Treść
                  </label>
                  <Textarea
                    id="rejection-email-body"
                    rows={7}
                    value={editDraft.body}
                    maxLength={5000}
                    invalid={bodyEmpty}
                    onChange={(e) => setDraft({ ...editDraft, body: e.target.value })}
                  />
                  {bodyEmpty ? (
                    <p className="text-xs text-destructive">
                      Treść maila nie może być pusta. Wpisz treść albo odznacz wysyłkę.
                    </p>
                  ) : null}
                </div>
                <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                  <PenLine className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  Pod treścią NEXUS doda Twój podpis z Outlooka. Mail wyjdzie z Twojej
                  skrzynki Microsoft 365.
                </p>
              </div>
            </div>
          ) : data && defaults ? (
            <div className="rounded-lg border border-primary/30">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-t-lg border-b border-border bg-primary/5 px-3 py-1.5">
                <span className="text-xs font-semibold uppercase tracking-[0.06em] text-primary">
                  {firstName ? `Podgląd maila · ${firstName}` : "Podgląd maila"}
                </span>
                <Badge variant="outline" size="sm">
                  tylko do odczytu
                </Badge>
              </div>
              <div className="space-y-2 p-3 text-sm">
                <p className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2">
                  <span className="text-xs text-muted-foreground">Temat</span>
                  <span>{defaults.subject}</span>
                </p>
                <p className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2">
                  {defaults.body}
                </p>
                <p className="text-xs text-muted-foreground">
                  Każda osoba dostanie tę treść ze swoim imieniem. Treść poprawisz,
                  odrzucając osoby pojedynczo.
                </p>
                <div className="space-y-1 text-xs">
                  <p className="text-muted-foreground">
                    Mail wyjdzie do {eligible.length} z {people.length} osób
                  </p>
                  <ul className="divide-y divide-dashed divide-border">
                    {people.map((p) => {
                      const name =
                        preview.people.find((x) => x.candidateId === p.candidate_id)
                          ?.name ?? `#${p.candidate_id}`;
                      return (
                        <li key={p.candidate_id} className="flex justify-between gap-2 py-1">
                          <span className={p.skip_reason ? "text-muted-foreground" : ""}>
                            {name}
                          </span>
                          <span className="text-right text-muted-foreground">
                            {p.skip_reason
                              ? `bez maila: ${rejectionEmailSkipShort(p.skip_reason)}`
                              : p.to_email}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </FormField>
  );
}

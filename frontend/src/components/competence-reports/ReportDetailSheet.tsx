"use client";

import { useState } from "react";
import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { useReport, useReportAction, type ReportAction } from "@/lib/competence-reports/api";
import {
  canEdit,
  canHold,
  canRelease,
  canSendNow,
  formatDeadline,
  formatWhen,
  statusChips,
  type ReportDetail,
} from "@/lib/competence-reports/logic";
import { hasCapability } from "@/lib/capabilities";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

import { ConditionsForm } from "./ConditionsForm";
import { CHIP_VARIANT, DEADLINE_CLASS } from "./tones";

const SUCCESS: Record<ReportAction["kind"], string> = {
  "send-now": "Raport wysłany.",
  hold: "Raport wstrzymany — nie wyjdzie sam.",
  release: "Raport zwolniony — wyjdzie sam w terminie.",
  conditions: "Warunki poprawione, raport przeliczony.",
  owner: "Opiekun zmieniony.",
};

const FAILURE: Record<ReportAction["kind"], string> = {
  "send-now": "Nie udało się wysłać raportu.",
  hold: "Nie udało się wstrzymać raportu.",
  release: "Nie udało się zwolnić raportu.",
  conditions: "Nie udało się zapisać warunków.",
  owner: "Nie udało się zmienić opiekuna.",
};

export function ReportDetailSheet({
  reportId,
  now,
  onClose,
}: {
  reportId: number | null;
  now: Date;
  onClose: () => void;
}) {
  const query = useReport(reportId);
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });

  return (
    <Sheet open={reportId != null} onOpenChange={(open) => (open ? null : onClose())}>
      <SheetContent size="2xl" className="w-full">
        {query.data && reportId != null ? (
          <ReportDetailBody key={reportId} report={query.data} now={now} />
        ) : (
          <>
            <SheetHeader>
              <SheetTitle>Raport kompetencji</SheetTitle>
            </SheetHeader>
            <SheetBody>
              {viewState === "loading" ? (
                <p className="text-sm text-muted-foreground">Ładowanie…</p>
              ) : (
                <QueryStateNotice
                  state={viewState === "ready" || viewState === "empty" ? "error" : viewState}
                  description={apiErrorMessage(query.error, "Nie udało się wczytać raportu.")}
                  onRetry={() => void query.refetch()}
                />
              )}
            </SheetBody>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

function ReportDetailBody({ report, now }: { report: ReportDetail; now: Date }) {
  const user = useAuthStore((state) => state.user);
  // Lustro `CandidateWriteAccess`: rola tylko do odczytu widzi raport bez przycisków.
  const mayAct = hasCapability(user, "candidate.write");
  const action = useReportAction(report.id);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const [editing, setEditing] = useState(false);
  const [ownerChoice, setOwnerChoice] = useState<string>("");
  const deadline = formatDeadline(report, now);

  async function run(next: ReportAction): Promise<boolean> {
    try {
      await action.mutateAsync(next);
      showSuccess(SUCCESS[next.kind]);
      return true;
    } catch (error) {
      showError(apiErrorMessage(error, FAILURE[next.kind]));
      return false;
    }
  }

  async function sendNow() {
    const ok = await askConfirm({
      title: "Wysłać raport teraz?",
      description: `Mail z raportem trafi od razu na adres ${report.email}. Tego nie da się cofnąć.`,
      confirmLabel: "Wyślij teraz",
    });
    if (ok) await run({ kind: "send-now" });
  }

  async function hold() {
    const ok = await askConfirm({
      title: "Wstrzymać raport?",
      description:
        "Kandydat dostał na stronie obietnicę raportu w 24 godziny. Wstrzymany raport nie wyjdzie sam — " +
        `termin mija ${formatWhen(report.send_due_at)}. Wyślij go albo zwolnij przed terminem.`,
      confirmLabel: "Wstrzymaj",
      variant: "destructive",
    });
    if (ok) await run({ kind: "hold" });
  }

  const choices = report.owner_choices.filter((p) => p.id !== report.owner?.id);

  return (
    <>
      <SheetHeader>
        <SheetTitle>
          <Link
            href={`/candidates/${report.candidate.id}`}
            className="hover:text-primary hover:underline"
          >
            {report.candidate.name}
          </Link>
        </SheetTitle>
        <SheetDescription>
          {report.role_label ?? "Rola po odczycie CV"} · {report.conditions_summary}
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="space-y-5">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-muted-foreground">Stan</dt>
            <dd className="mt-0.5 flex flex-wrap gap-1">
              {statusChips(report).map((chip) => (
                <Badge key={chip.label} variant={CHIP_VARIANT[chip.tone]}>
                  {chip.label}
                </Badge>
              ))}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Wysyłka</dt>
            <dd className={cn("mt-0.5 font-medium tabular-nums", DEADLINE_CLASS[deadline.tone])}>
              {report.sent_at
                ? `wysłany ${formatWhen(report.sent_at)}${report.sent_by ? ` · ${report.sent_by.name}` : " · sam"}`
                : `${deadline.text} · ${formatWhen(report.send_due_at)}`}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Opiekun</dt>
            <dd className="mt-0.5 text-foreground">{report.owner?.name ?? "bez opiekuna"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Adres</dt>
            <dd className="mt-0.5 truncate text-foreground" title={report.email}>
              {report.email}
            </dd>
          </div>
        </dl>

        {report.held ? (
          <Alert
            variant="warning"
            title={`Wstrzymany${report.held_by ? ` przez: ${report.held_by.name}` : ""}`}
            description={report.warning ?? undefined}
          />
        ) : null}
        {report.status === "failed" && report.last_error ? (
          <Alert
            variant="error"
            title="Ostatnia wysyłka się nie udała"
            description={`Próby: ${report.attempts}. Możesz wysłać raport ponownie.`}
          />
        ) : null}

        {mayAct ? (
          <div className="flex flex-wrap items-center gap-2">
            {canSendNow(report) ? (
              <Button size="sm" onClick={() => void sendNow()} loading={action.isPending}>
                Wyślij teraz
              </Button>
            ) : null}
            {canHold(report) ? (
              <Button size="sm" variant="outline" onClick={() => void hold()} disabled={action.isPending}>
                Wstrzymaj
              </Button>
            ) : null}
            {canRelease(report) ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void run({ kind: "release" })}
                disabled={action.isPending}
              >
                Zwolnij wstrzymanie
              </Button>
            ) : null}
            {canEdit(report) && !editing ? (
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                Popraw warunki
              </Button>
            ) : null}
            {canEdit(report) ? (
              <div className="flex items-center gap-2">
                <Select value={ownerChoice} onValueChange={setOwnerChoice} disabled={choices.length === 0}>
                  <SelectTrigger className="h-8 w-56" aria-label="Nowy opiekun">
                    <SelectValue
                      placeholder={choices.length === 0 ? "Brak innych opiekunów" : "Zmień opiekuna…"}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {choices.map((person) => (
                      <SelectItem key={person.id} value={String(person.id)}>
                        {person.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {ownerChoice ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={action.isPending}
                    onClick={async () => {
                      if (await run({ kind: "owner", userId: Number(ownerChoice) })) setOwnerChoice("");
                    }}
                  >
                    Przekaż
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {editing ? (
          <ConditionsForm
            initial={report.conditions}
            saving={action.isPending}
            onCancel={() => setEditing(false)}
            onSave={async (body) => {
              if (await run({ kind: "conditions", body })) setEditing(false);
            }}
          />
        ) : null}

        <section aria-labelledby="report-preview" className="space-y-2">
          <h3 id="report-preview" className="text-sm font-semibold text-foreground">
            Podgląd maila
          </h3>
          {report.preview_html ? (
            <>
              <p className="text-xs text-muted-foreground">Temat: {report.preview_subject}</p>
              {/* Pusty `sandbox`: bez skryptów i bez formularzy — mail to sam HTML z tabelami. */}
              <iframe
                title={`Podgląd raportu: ${report.candidate.name}`}
                sandbox=""
                srcDoc={report.preview_html}
                className="h-[60dvh] w-full rounded-lg border border-border bg-card"
              />
            </>
          ) : (
            <p className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
              {report.status === "waiting_cv"
                ? "Raport powstanie po odczycie CV — zwykle w ciągu godziny od zgłoszenia."
                : "Ten raport nie ma treści do podglądu."}
            </p>
          )}
        </section>
      </SheetBody>
      {confirmDialog}
    </>
  );
}

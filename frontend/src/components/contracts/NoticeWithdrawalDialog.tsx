"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  contractsApi,
  type ContractNoticeWithdrawalPreview,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { ContractDocument } from "@/lib/contract-document-folders";
import { formatIsoDatePl } from "@/lib/date-pl";
import { AppModal } from "@/components/ds/AppModal";
import {
  ReverseTerminationPlanView,
  invalidateAfterRecovery,
} from "@/components/contracts/ContractTerminationRecovery";

/**
 * „Wycofaj wypowiedzenie” (zgłoszenie Finansów 17.11.2026): konsultant
 * wycofał wypowiedzenie zapisane aneksem „Wcześniejsze zakończenie”. Człowiek
 * wybiera nową datę końca umowy (B2B domyślnie bez daty); zakończony kontrakt
 * wraca razem z zamówieniami tą samą drogą co „Cofnij zakończenie”.
 */

export type NoticeEndChoice = "indefinite" | "before_notice" | "custom";

export interface NoticeEndOption {
  value: NoticeEndChoice;
  label: string;
  hint?: string;
}

/** Opcje daty końca dostępne dla tego wypowiedzenia, rekomendowana pierwsza. */
export function noticeEndOptions(
  preview: Pick<
    ContractNoticeWithdrawalPreview,
    "indefinite_allowed" | "earliest_end_date" | "notice"
  >,
): NoticeEndOption[] {
  const options: NoticeEndOption[] = [];
  if (preview.indefinite_allowed) {
    options.push({
      value: "indefinite",
      label: "Umowa bezterminowa",
      hint: "Umowa B2B bez daty końca, jak przed wypowiedzeniem.",
    });
  }
  const before = preview.notice.end_before_notice;
  if (before && before >= preview.earliest_end_date) {
    options.push({
      value: "before_notice",
      label: `Wraca data sprzed wypowiedzenia: ${formatIsoDatePl(before)}`,
    });
  }
  options.push({
    value: "custom",
    label: "Inna data końca",
    hint: `od ${formatIsoDatePl(preview.earliest_end_date)}`,
  });
  return options;
}

/** Data końca do wysłania (`null` = bezterminowo) albo `undefined`, gdy brak. */
export function noticeEndDate(
  choice: NoticeEndChoice,
  preview: Pick<ContractNoticeWithdrawalPreview, "notice">,
  customDate: string,
): string | null | undefined {
  if (choice === "indefinite") return null;
  if (choice === "before_notice") return preview.notice.end_before_notice ?? undefined;
  return customDate || undefined;
}

const CONTRACT_STATUS_LABEL: Record<string, string> = {
  active: "Aktywny",
  ending: "Kończący się",
  ended: "Zakończony",
};

export function NoticeWithdrawalDialog({
  contractId,
  onClose,
}: {
  contractId: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const preview = useQuery({
    queryKey: ["contract-notice-withdrawal", contractId],
    queryFn: async () => (await contractsApi.noticeWithdrawalPreview(contractId)).data,
    staleTime: 0,
  });
  const docs = useQuery<ContractDocument[]>({
    queryKey: ["contract-documents", contractId],
    queryFn: () => contractsApi.documents(contractId).then((r) => r.data),
  });
  const [choice, setChoice] = useState<NoticeEndChoice | null>(null);
  const [customDate, setCustomDate] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [note, setNote] = useState("");

  const data = preview.data;
  const options = data ? noticeEndOptions(data) : [];
  const selected = choice ?? options[0]?.value ?? "custom";
  const endDate = data ? noticeEndDate(selected, data, customDate) : undefined;
  const customTooEarly =
    selected === "custom" && !!data && !!customDate && customDate < data.earliest_end_date;
  const blocked = (data?.reversal?.blockers.length ?? 0) > 0;
  const canSubmit = !!data && endDate !== undefined && !customTooEarly && !blocked;

  const mut = useMutation({
    mutationFn: async () =>
      (
        await contractsApi.withdrawNotice(contractId, {
          end_date: endDate ?? null,
          note: note.trim() || null,
          document_id: documentId ? Number(documentId) : null,
        })
      ).data,
    onSuccess: () => {
      invalidateAfterRecovery(qc, contractId);
      qc.invalidateQueries({ queryKey: ["contract-amendments", contractId] });
      qc.invalidateQueries({ queryKey: ["contract-termination-reversal", contractId] });
      onClose();
    },
  });

  const formId = `notice-withdrawal-${contractId}`;
  return (
    <AppModal
      open
      size="lg"
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Wycofaj wypowiedzenie"
      description="Konsultant wycofał wypowiedzenie — umowa trwa dalej."
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-muted-foreground hover:underline"
          >
            Anuluj
          </button>
          <button
            type="submit"
            form={formId}
            disabled={!canSubmit || mut.isPending}
            className="text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-md px-4 py-2"
          >
            {mut.isPending ? "Zapisywanie…" : "Wycofaj wypowiedzenie"}
          </button>
        </>
      }
    >
      {preview.isLoading && (
        <p className="text-sm text-muted-foreground">Sprawdzam wypowiedzenie…</p>
      )}
      {preview.isError && (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(preview.error, "Nie udało się przygotować podglądu.")}
        </p>
      )}
      {preview.isSuccess && data && (
        <form
          id={formId}
          className="space-y-4 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) mut.mutate();
          }}
        >
          <p className="rounded-md border border-primary/30 bg-primary/5 p-3">
            Wypowiedzenie z {formatIsoDatePl(data.notice.effective_date)} skróciło
            umowę
            {data.notice.end_before_notice
              ? ` z ${formatIsoDatePl(data.notice.end_before_notice)}`
              : ""}{" "}
            do {formatIsoDatePl(data.notice.notice_end)}.
          </p>

          <fieldset className="space-y-2">
            <legend className="text-xs font-semibold uppercase text-muted-foreground">
              Data końca umowy po wycofaniu
            </legend>
            {options.map((option) => (
              <label
                key={option.value}
                className={`flex items-start gap-2 rounded-md border p-2 ${
                  selected === option.value ? "border-primary bg-primary/5" : "border-border"
                }`}
              >
                <input
                  type="radio"
                  name={`${formId}-end`}
                  value={option.value}
                  checked={selected === option.value}
                  onChange={() => setChoice(option.value)}
                  className="mt-1"
                />
                <span className="min-w-0">
                  <span className="font-medium">{option.label}</span>
                  {option.hint && (
                    <span className="block text-xs text-muted-foreground">{option.hint}</span>
                  )}
                  {option.value === "custom" && selected === "custom" && (
                    <input
                      type="date"
                      aria-label="Nowa data końca umowy"
                      min={data.earliest_end_date}
                      value={customDate}
                      onChange={(e) => setCustomDate(e.target.value)}
                      className="mt-1 block border border-border rounded-md px-3 py-1.5 text-sm bg-card"
                    />
                  )}
                </span>
              </label>
            ))}
            {customTooEarly && (
              <p role="alert" className="text-xs text-destructive">
                Data końca musi być dzisiejsza albo późniejsza.
              </p>
            )}
          </fieldset>

          <label className="block">
            <span className="text-xs text-muted-foreground">
              Dokument wycofania (opcjonalnie, z zakładki Dokumenty)
            </span>
            <select
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
              className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-card"
            >
              <option value="">Bez dokumentu</option>
              {(docs.data ?? []).map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.filename}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="text-xs text-muted-foreground">Notatka (opcjonalnie)</span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={2000}
              className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-card"
            />
          </label>

          <section>
            <h4 className="text-xs font-semibold uppercase text-muted-foreground">Kontrakt</h4>
            <ul className="mt-1 space-y-0.5">
              <li>
                Status: {CONTRACT_STATUS_LABEL[data.status] ?? data.status} →{" "}
                <strong>Aktywny</strong>
              </li>
              <li>
                Data końca umowy:{" "}
                {data.end_date ? formatIsoDatePl(data.end_date) : "bezterminowo"} →{" "}
                <strong>
                  {endDate === null
                    ? "bezterminowo"
                    : endDate
                      ? formatIsoDatePl(endDate)
                      : "—"}
                </strong>
              </li>
              <li>
                Aneks z {formatIsoDatePl(data.notice.effective_date)} dostanie status
                „Wycofany”, a w Aneksach pojawi się wpis „Wycofanie wypowiedzenia”.
              </li>
            </ul>
          </section>

          {data.reversal ? (
            <ReverseTerminationPlanView plan={data.reversal} showContract={false} />
          ) : (
            <p className="text-xs text-muted-foreground">
              Wypowiedzenie jeszcze nie zakończyło umowy — zamówienia zostają bez
              zmian.
            </p>
          )}

          {mut.isError && (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(mut.error, "Nie udało się wycofać wypowiedzenia.")}
            </p>
          )}
        </form>
      )}
    </AppModal>
  );
}

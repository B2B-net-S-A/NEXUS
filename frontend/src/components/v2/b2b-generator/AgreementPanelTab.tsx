"use client";

/**
 * Umowa w rozwiniętym panelu osoby (zakładka „Umowa”, 04.10.2026).
 *
 * Rekruter generuje umowę dla swojego kandydata tam, gdzie prowadzi proces —
 * to ten sam formularz co w Generatorze (`GeneratorForm` z ustaloną parą)
 * i ten sam wiersz rejestru, więc Generator jest lustrem tej zakładki.
 *  - brak żywej umowy pary: formularz z podpowiedziami z rekrutacji,
 *  - jest umowa: numer, stan, „Pobierz DOCX”, „Popraw umowę” (ten sam numer,
 *    `can_edit` liczy serwer: autor, zespół rekrutacji, TCM, admin) i podpis.
 * Formularz ładuje się leniwie — moduł Generatora jest duży.
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, PencilLine } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AgreementSignatureAction,
  invalidateAgreementQueries,
} from "@/components/v2/b2b-generator/AgreementSignatureAction";
import { hasActionAccess } from "@/lib/action-access";
import { b2bGeneratorApi, type B2BGeneratedContractRow } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { CardAgreement } from "@/lib/b2b-agreement";
import { registerSearchHref } from "@/lib/b2b-generator-register";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

const GeneratorForm = dynamic(
  () => import("@/components/v2/pages/B2BContractGeneratorV2").then((m) => m.GeneratorForm),
  {
    ssr: false,
    loading: () => (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Wczytuję formularz umowy…
      </p>
    ),
  },
);

const STATUS_LABEL: Record<string, string> = {
  in_progress: "W trakcie",
  active: "Aktywna",
  cancelled: "Anulowana",
  closed: "Zakończona",
  suspended: "Bez projektu",
};

/** Żywa umowa pary — anulowana, zakończona i „bez projektu” się nie liczą. */
export function liveAgreementRow(
  rows: B2BGeneratedContractRow[] | undefined,
  candidateId: number,
): B2BGeneratedContractRow | null {
  return (
    (rows ?? []).find(
      (r) =>
        r.candidate_id === candidateId &&
        (r.contract_status === "in_progress" || r.contract_status === "active"),
    ) ?? null
  );
}

export function AgreementPanelTab({
  candidateId,
  jobId,
  readOnly,
  agreement = null,
}: {
  candidateId: number;
  jobId: number;
  readOnly: boolean;
  agreement?: CardAgreement | null;
}) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const user = useAuthStore((s) => s.user);
  const canGenerate =
    hasSectionAccess(user, "sourcing", "write") &&
    hasActionAccess(user, "b2b_contract_generator", "generate");
  const [editing, setEditing] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // Ten sam klucz co sekcja w wąskim panelu i warsztat — jedno zapytanie.
  const contracts = useQuery<B2BGeneratedContractRow[]>({
    queryKey: ["b2b-generated", "job", jobId],
    queryFn: () => b2bGeneratorApi.generated(50, { jobId }),
    staleTime: 60_000,
  });
  const row = liveAgreementRow(contracts.data, candidateId);

  const onSaved = () => {
    setEditing(false);
    invalidateAgreementQueries(queryClient, jobId);
  };

  const download = async (target: B2BGeneratedContractRow) => {
    setDownloading(true);
    try {
      const res = await b2bGeneratorApi.downloadGenerated(target.id);
      const filename = parseDispositionFilename(
        res.headers["content-disposition"] || "",
        `Umowa B2B ${target.contract_number.replaceAll("/", "-")}.docx`,
      );
      downloadBlob(res.data as Blob, filename);
    } catch (e) {
      showError(apiErrorMessage(e, "Nie udało się pobrać umowy."));
    } finally {
      setDownloading(false);
    }
  };

  if (contracts.isLoading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Sprawdzam umowę…
      </p>
    );
  }
  if (contracts.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Nie udało się sprawdzić umowy.{" "}
        <button type="button" className="font-medium underline" onClick={() => void contracts.refetch()}>
          Ponów
        </button>
      </p>
    );
  }

  if (!row || editing) {
    if (readOnly || !canGenerate) {
      return (
        <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          {readOnly
            ? "Ta osoba nie ma jeszcze umowy."
            : "Ta osoba nie ma jeszcze umowy. Generowanie umów wymaga uprawnienia do Generatora umów B2B."}
        </p>
      );
    }
    return (
      <section aria-label="Umowa B2B" className="space-y-2" data-testid="agreement-panel-form">
        {editing && row ? (
          <div className="flex items-center justify-between gap-2 rounded-md bg-muted/40 px-3 py-2 text-sm">
            <span>Poprawiasz umowę {row.contract_number} — numer zostaje ten sam.</span>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Anuluj poprawkę
            </Button>
          </div>
        ) : null}
        <GeneratorForm
          lockedPair
          prefillCandidateId={candidateId}
          prefillJobId={jobId}
          editGeneratedId={editing && row ? row.id : null}
          onSaved={onSaved}
        />
      </section>
    );
  }

  const signed = row.signature_status === "signed_both";
  return (
    <section
      aria-label="Umowa B2B"
      className="space-y-3 rounded-lg border border-border p-3"
      data-testid="agreement-panel-state"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">Umowa {row.contract_number}</span>
        <Badge variant={signed ? "success" : "info"}>
          {signed ? "Podpisana obustronnie" : (STATUS_LABEL[row.contract_status] ?? row.contract_status)}
        </Badge>
        <Link
          href={registerSearchHref(row.contract_number, row.contract_status)}
          className="ml-auto text-xs text-muted-foreground hover:text-foreground hover:underline"
        >
          W rejestrze ↗
        </Link>
      </div>
      <p className="text-xs text-muted-foreground">
        Wygenerowana
        {row.created_at ? ` ${formatIsoDatePl(row.created_at.slice(0, 10))}` : ""}
        {row.created_by_name ? ` przez ${row.created_by_name}` : ""}.
        {signed
          ? " Kontrakt i zamówienie są w Delivery."
          : " Wyślij DOCX Partnerowi; po podpisie obu stron potwierdź podpis."}
      </p>
      <div className="flex flex-wrap items-start gap-2">
        {row.can_download ? (
          <Button size="sm" variant="outline" disabled={downloading} onClick={() => void download(row)}>
            <Download className="h-3.5 w-3.5" aria-hidden />
            Pobierz DOCX
          </Button>
        ) : null}
        {!readOnly && canGenerate && row.can_edit && !signed ? (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            <PencilLine className="h-3.5 w-3.5" aria-hidden />
            Popraw umowę
          </Button>
        ) : null}
        <AgreementSignatureAction
          row={row}
          jobId={jobId}
          requestedAt={agreement?.signature_requested_at ?? null}
          readOnly={readOnly}
        />
      </div>
    </section>
  );
}

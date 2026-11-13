"use client";

// Finanse → Rozliczenia → lista miesiąca: arkusze zbiorcze per osoba podpisująca
// u klienta (roadmapa E6.2, Velo; reguła `cl.client_document` na „podpisującego”).
// Każdy arkusz do pobrania osobno, żeby wysłać go od razu, gdy jest gotowy
// (uwaga rozliczeń z 12.11), obok „Pobierz wszystkie”. Podpisany arkusz NEXUS
// rozpoznaje po treści, niezależnie od tego, kto go wrzucił.
import { Download } from "lucide-react";

import { StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import {
  fetchClientDocumentFile,
  type ClientDocumentFileKind,
  type ClientDocumentsMonth,
} from "@/lib/api/client-settlements";

import { STATUS, mdText, monthLabel, pln } from "./format";
import { SignedDocumentUpload } from "./SignedDocumentUpload";

const NO_SIGNER = "Bez podpisującego";

function peopleText(n: number): string {
  return n === 1 ? "1 osoba" : n % 10 >= 2 && n % 10 <= 4 && (n < 10 || n > 20) ? `${n} osoby` : `${n} osób`;
}

function signedWhen(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return y && m && d ? `, ${d}.${m}` : "";
}

function fileSafe(text: string): string {
  return text.replace(/[^\p{L}\p{N}.-]+/gu, "_");
}

export function SignerSheetsPanel({ data, clientId }: { data: ClientDocumentsMonth; clientId: number }) {
  const { showError } = useToast();
  const sheets = data.sheets;
  if (!sheets) return null;
  const month = data.month;

  async function onDownload(kind: ClientDocumentFileKind, name: string, signer?: string) {
    try {
      downloadBlob(await fetchClientDocumentFile(clientId, month, kind, signer), name);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać arkusza."));
    }
  }

  const signed = sheets.rows.filter((r) => r.signed).length;

  return (
    <section aria-label={data.kind} className="rounded-xl border border-primary/25 bg-primary/[0.04] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-[78ch]">
          <h2 className="text-sm font-semibold">
            Arkusze zbiorcze za {monthLabel(month)}: {sheets.signers.length} podpisujących, podpisane {signed} z{" "}
            {sheets.rows.length}
          </h2>
          <p className="text-xs text-muted-foreground">
            NEXUS układa osoby według podpisującego (menedżer u klienta w kontrakcie). Każdy arkusz pobierasz osobno i wysyłasz od
            razu, gdy jest gotowy. Konsultanta rozliczamy po podpisie jego arkusza, fakturę do klienta po wszystkich.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            disabled={sheets.signers.length === 0}
            onClick={() => onDownload("sheets", `Arkusze_zbiorcze_${month}.zip`)}
          >
            <Download aria-hidden className="size-3.5" /> Pobierz wszystkie
          </Button>
          {data.can_see_amounts ? (
            <Button
              size="sm"
              variant="outline"
              disabled={!sheets.all_signed}
              title={sheets.all_signed ? "Arkusz ze stawkami pod fakturę do klienta" : "Czeka na podpisy wszystkich arkuszy"}
              onClick={() => onDownload("invoice_sheet", `Arkusz_zbiorczy_wartosci_${month}.pdf`)}
            >
              <Download aria-hidden className="size-3.5" /> Arkusz pod fakturę
            </Button>
          ) : null}
          <SignedDocumentUpload month={month} label="Wgraj podpisany" />
        </div>
      </div>
      {sheets.signers.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">Nikt jeszcze nie ma MD za ten miesiąc.</p>
      ) : (
        <ul className="mt-2 grid gap-x-6 lg:grid-cols-2">
          {sheets.signers.map((g) => (
            <li key={g.signer} className="border-t py-1 text-[13px]">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
                <span className="font-medium">{g.signer}</span>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {peopleText(g.people)}, {mdText(g.md)} MD, podpisane {g.signed} z {g.people}
                </span>
                <button
                  type="button"
                  onClick={() => onDownload("sheet", `Arkusz_zbiorczy_${fileSafe(g.signer)}_${month}.pdf`, g.signer)}
                  className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline pointer-coarse:min-h-9"
                  aria-label={`Pobierz arkusz: ${g.signer}`}
                >
                  <Download aria-hidden className="size-3.5" /> Pobierz arkusz
                </button>
              </div>
              {g.signer === NO_SIGNER ? (
                <p className="text-[11px] text-warning-muted-foreground">Ustaw menedżera u klienta w kontrakcie tych osób.</p>
              ) : null}
              <ul className="mt-0.5 grid gap-0.5">
                {sheets.rows
                  .filter((r) => r.signer === g.signer)
                  .map((r) => (
                    <li key={r.contract_id} className="flex flex-wrap items-center gap-x-2 text-xs">
                      <span className="min-w-36">{r.person}</span>
                      <span className="tabular-nums text-muted-foreground">{mdText(r.md)} MD</span>
                      {r.amount ? <span className="tabular-nums text-muted-foreground">{pln(r.amount)}</span> : null}
                      {r.signed ? (
                        <StatusDot tone="success">
                          Podpisany{r.signed_by ? `: ${r.signed_by}` : ""}
                          {signedWhen(r.signed_at)}
                        </StatusDot>
                      ) : (
                        <StatusDot tone="warning">Do podpisu</StatusDot>
                      )}
                    </li>
                  ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {sheets.without_sheet.length > 0 ? (
        <p className="mt-1.5 text-xs text-muted-foreground">
          Poza arkuszami: {sheets.without_sheet.map((w) => `${w.person} (${STATUS[w.status].label.toLowerCase()})`).join(", ")}.
        </p>
      ) : null}
    </section>
  );
}

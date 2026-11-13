"use client";

// Karta osoby → KEŚU klienta z Jirą (roadmapa E6.3, Alior). NEXUS czyta mail
// z Jiry (opiekun, czas akceptacji) i KEŚU (godziny), wstawia stawkę MD
// z kontraktu i liczy „Razem w PLN BRUTTO”. Paczka do podpisu spółki to KEŚU
// i faktury kosztów w jednym PDF, a mail idzie do opiekuna z maila z Jiry.
// Faktura do klienta i zapłata konsultanta czekają na podpis klienta.
import { Copy, Download } from "lucide-react";

import { StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import { copyTextToClipboard } from "@/lib/clipboard";
import { fetchKesuPackage, usePayOnMail, type KesuBlock } from "@/lib/api/client-settlements";
import { cn } from "@/lib/utils";

import { KESU, pln } from "./format";

function when(iso: string | null): string | null {
  if (!iso) return null;
  const [day, time] = iso.split("T");
  const [y, m, d] = day.split("-");
  return `${d}.${m}.${y}${time ? ` ${time.slice(0, 5)}` : ""}`;
}

function hoursText(block: KesuBlock): string {
  const hours = block.hours ? Number(block.hours).toLocaleString("pl-PL", { maximumFractionDigits: 2 }) : "–";
  return `${hours} h, ${block.days ?? 0} dni`;
}

interface KesuSectionProps {
  contractId: number;
  month: string;
  person: string;
  block: KesuBlock;
  canWrite: boolean;
}

export function KesuSection({ contractId, month, person, block, canWrite }: KesuSectionProps) {
  const payOnMail = usePayOnMail(month);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const amounts = block.rate_md != null;
  const accepted = [block.approver, when(block.accepted_at)].filter(Boolean).join(", ");

  async function onPackage() {
    try {
      const blob = await fetchKesuPackage(contractId, month);
      const safe = person.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/ł/g, "l").replace(/Ł/g, "L").replace(/[^A-Za-z0-9]+/g, "_");
      const [y, m] = month.split("-");
      downloadBlob(blob, `KESU_${safe}_${m}.${y}.pdf`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się złożyć paczki KEŚU."));
    }
  }

  async function onCopyMail() {
    const text = [`Do: ${block.mail.to ?? block.mail.to_name ?? "—"}`, `Temat: ${block.mail.subject}`, "", block.mail.body].join("\n");
    if (await copyTextToClipboard(text)) {
      showSuccess("Skopiowano mail do opiekuna. Dołącz podpisaną paczkę PDF.");
    } else {
      showError("Nie udało się skopiować maila. Spróbuj ponownie w tej karcie przeglądarki.");
    }
  }

  async function onPayOnMail() {
    const ok = await askConfirm({
      title: "Zapłacić po akceptacji mailowej?",
      description:
        "Tylko gdy podpisujący KEŚU jest nieobecny i nie ma zastępstwa. Podpisane KEŚU zostaje do sprawdzenia, gdy wróci.",
      confirmLabel: "Zapłać po mailu",
    });
    if (!ok) return;
    try {
      await payOnMail.mutateAsync(contractId);
      showSuccess("Zapłata po akceptacji mailowej. Podpisane KEŚU sprawdzimy później.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać zapłaty po mailu."));
    }
  }

  return (
    <section aria-label="KEŚU" className="min-w-0 rounded-xl border bg-card p-3">
      {confirmDialog}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">KEŚU z Jiry</h3>
        <StatusDot tone={KESU[block.state].tone}>{KESU[block.state].label}</StatusDot>
      </div>
      <dl className="mt-1.5 grid grid-cols-[minmax(0,40%)_minmax(0,1fr)] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-muted-foreground">Akceptacja opiekuna</dt>
        <dd className="min-w-0 truncate">{accepted || "brak maila z Jiry"}</dd>
        <dt className="text-muted-foreground">Czas</dt>
        <dd className="tabular-nums">{hoursText(block)}</dd>
        {amounts ? (
          <>
            <dt className="text-muted-foreground">Stawka MD z kontraktu</dt>
            <dd className="tabular-nums">{pln(block.rate_md)} netto</dd>
            {block.rate_differs ? (
              <>
                <dt className="text-warning-muted-foreground">Na zamówieniu</dt>
                <dd className="tabular-nums text-warning-muted-foreground">
                  {pln(block.rate_order)}, różnica {pln(String(Number(block.rate_contract) - Number(block.rate_order)))}
                </dd>
              </>
            ) : null}
            {block.extra_costs && Number(block.extra_costs) > 0 ? (
              <>
                <dt className="text-muted-foreground">Koszty dodatkowe</dt>
                <dd className="tabular-nums">{pln(block.extra_costs)} brutto</dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">Razem w PLN BRUTTO</dt>
            <dd className="font-semibold tabular-nums">{pln(block.total_gross)}</dd>
          </>
        ) : null}
      </dl>
      {block.payment ? (
        <p
          className={cn(
            "mt-2 rounded-md px-2 py-1.5 text-[12px]",
            block.payment.state === "ok"
              ? "bg-success-muted text-success-muted-foreground"
              : block.payment.state === "fail"
                ? "bg-destructive-muted text-destructive-muted-foreground"
                : "bg-warning-muted text-warning-muted-foreground",
          )}
        >
          <span className="font-medium">{block.payment.title}.</span> {block.payment.detail}
        </p>
      ) : null}
      {block.invoice_waits ? (
        <p className="mt-1.5 text-[12px] text-muted-foreground">Faktura do klienta: dopiero po podpisie klienta.</p>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {amounts && block.package_ready && block.state !== "signed" ? (
          <Button size="sm" variant="outline" onClick={onPackage}>
            <Download aria-hidden className="size-3.5" /> Paczka do podpisu (PDF)
          </Button>
        ) : null}
        {block.state !== "signed" ? (
          <Button size="sm" variant="outline" onClick={onCopyMail} title={block.mail.to ?? undefined}>
            <Copy aria-hidden className="size-3.5" /> Mail do opiekuna
          </Button>
        ) : null}
        {canWrite && block.payment?.can_use_mail ? (
          <Button size="sm" variant="outline" disabled={payOnMail.isPending} onClick={onPayOnMail}>
            Podpisujący nieobecny
          </Button>
        ) : null}
      </div>
    </section>
  );
}

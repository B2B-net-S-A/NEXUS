"use client";

import { Copy } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import type {
  InvoiceMail,
  InvoiceRequirement,
} from "@/lib/api/issued-invoices";

interface InvoiceRequirementsBoxProps {
  requirements: InvoiceRequirement[];
  mail: InvoiceMail | null;
  warnings: string[];
}

/**
 * Wymagania klienta do faktury (reguły `cl.*` w „Reguły klienta”, 23.11.2026):
 * co NEXUS wpisze do KSeF (numery zamówień, umowa, pola dodatkowe), co sprawdza
 * w pozycjach i gdzie wysłać fakturę mailem obok KSeF. Zmiana — w regułach klienta.
 */
export function InvoiceRequirementsBox({
  requirements,
  mail,
  warnings,
}: InvoiceRequirementsBoxProps) {
  const { showToast } = useToast();
  if (!requirements.length && !mail && !warnings.length) return null;

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast(`Skopiowano ${what}`, "success");
    } catch {
      showToast("Nie udało się skopiować — zaznacz tekst ręcznie.", "error");
    }
  };

  return (
    <section
      className="rounded-lg border border-border bg-card px-4 py-3 text-sm"
      aria-label="Wymagania klienta"
    >
      <h3 className="mb-2 text-sm font-semibold text-foreground">
        Wymagania klienta
      </h3>
      {requirements.length ? (
        <dl className="space-y-1">
          {requirements.map((item) => (
            <div key={item.label}>
              <dt className="text-xs text-muted-foreground">{item.label}</dt>
              <dd className="break-words text-foreground">{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {warnings.length ? (
        <ul className="mt-2 list-disc pl-5 text-xs text-warning">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {mail ? (
        <div className="mt-2 border-t border-border pt-2">
          <p className="text-xs text-muted-foreground">
            Mail z fakturą obok KSeF{mail.attach ? ` (załącz: ${mail.attach})` : ""}
          </p>
          <div className="mt-1 flex items-start justify-between gap-2">
            <span className="break-all text-foreground">{mail.email}</span>
            <Button
              size="sm"
              variant="ghost"
              aria-label="Kopiuj adres"
              onClick={() => copy(mail.email, "adres")}
            >
              <Copy className="h-4 w-4" aria-hidden />
            </Button>
          </div>
          <div className="mt-1 flex items-start justify-between gap-2">
            <span className="break-words text-foreground">{mail.subject}</span>
            <Button
              size="sm"
              variant="ghost"
              aria-label="Kopiuj temat"
              onClick={() => copy(mail.subject, "temat")}
            >
              <Copy className="h-4 w-4" aria-hidden />
            </Button>
          </div>
        </div>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">
        Z reguł klienta (Rozliczenia → Reguły klienta → Faktura do klienta).
      </p>
    </section>
  );
}

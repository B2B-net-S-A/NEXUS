"use client";

import { useEffect, useRef, useState } from "react";
import { FileDown, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import type {
  AgreementVersion,
  TrainingPartner,
  TrainingPartnerResponse,
  TrainingView,
} from "@/lib/api/trainings";
import { formatDateTimePl } from "@/lib/date-pl";

const PARTNER_FIELDS: { key: keyof TrainingPartner; label: string; required?: boolean }[] = [
  { key: "full_name", label: "Imię i nazwisko", required: true },
  { key: "company", label: "Nazwa firmy", required: true },
  { key: "address", label: "Adres działalności", required: true },
  { key: "postal_city", label: "Kod i miejscowość" },
  { key: "nip", label: "NIP", required: true },
  { key: "regon", label: "REGON" },
  { key: "phone", label: "Telefon" },
  { key: "email", label: "E-mail trenera", required: true },
];

export function partnerFromResponse(data: TrainingPartnerResponse | undefined): TrainingPartner {
  const source = data?.partner ?? {};
  const text = (key: keyof TrainingPartner) =>
    typeof source[key] === "string" ? (source[key] as string) : "";
  return {
    full_name: text("full_name"),
    company: text("company"),
    address: text("address"),
    postal_city: text("postal_city"),
    nip: text("nip"),
    regon: text("regon"),
    phone: text("phone"),
    email: text("email"),
  };
}

/** Polskie nazwy brakujących pól wymaganych (lustro `agreement.missing_partner_fields`). */
export function missingPartnerFields(partner: TrainingPartner): string[] {
  return PARTNER_FIELDS.filter((field) => field.required && !partner[field.key].trim()).map(
    (field) => field.label.toLowerCase(),
  );
}

interface AgreementPanelProps {
  view: Pick<TrainingView, "status" | "trainer_kind" | "agreement">;
  canManage: boolean;
  isCompanySigner: boolean;
  /** Dane trenera do umowy (tylko TCM i tylko przy wycenie przyjętej). */
  partner?: TrainingPartnerResponse;
  partnerError?: string | null;
  onDownload: (version: AgreementVersion) => void;
  onGenerate: (input: { partner: TrainingPartner; company_email: string }) => Promise<boolean>;
  onCompanySign: (file: File) => Promise<boolean>;
  busy?: boolean;
}

export function AgreementPanel({
  view,
  canManage,
  isCompanySigner,
  partner,
  partnerError = null,
  onDownload,
  onGenerate,
  onCompanySign,
  busy,
}: AgreementPanelProps) {
  const [form, setForm] = useState<TrainingPartner>(() => partnerFromResponse(partner));
  const [companyEmail, setCompanyEmail] = useState(partner?.company_email ?? "");
  const signInput = useRef<HTMLInputElement>(null);
  const { agreement, status } = view;

  // Dane z kontraktu dochodzą po pierwszym renderze — wypełnij formularz raz.
  const loaded = useRef(Boolean(partner));
  useEffect(() => {
    if (partner && !loaded.current) {
      loaded.current = true;
      setForm(partnerFromResponse(partner));
      setCompanyEmail(partner.company_email);
    }
  }, [partner]);

  if (view.trainer_kind === "employee") {
    return (
      <p className="text-sm text-muted-foreground">
        Szkolenie prowadzi pracownik, więc nie ma umowy B2B ani wyceny.
      </p>
    );
  }

  const canGenerate = canManage && status === "accepted" && !agreement.trainer_signed_at;
  const missing = missingPartnerFields(form);

  return (
    <div className="space-y-4">
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">Numer umowy</dt>
          <dd>{agreement.number ?? "jeszcze nie ma"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Przygotowana</dt>
          <dd>{formatDateTimePl(agreement.generated_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Podpis trenera</dt>
          <dd>{agreement.trainer_signed_at ? formatDateTimePl(agreement.trainer_signed_at) : "czeka"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Podpis B2B Network</dt>
          <dd>{agreement.company_signed_at ? formatDateTimePl(agreement.company_signed_at) : "czeka"}</dd>
        </div>
      </dl>

      <div className="flex flex-wrap gap-2">
        {agreement.generated_at ? (
          <Button size="sm" variant="outline" onClick={() => onDownload("draft")}>
            <FileDown className="h-3.5 w-3.5" aria-hidden /> Umowa do podpisu (PDF)
          </Button>
        ) : null}
        {agreement.trainer_signed_at ? (
          <Button size="sm" variant="outline" onClick={() => onDownload("trainer")}>
            <FileDown className="h-3.5 w-3.5" aria-hidden /> Podpisana przez trenera
          </Button>
        ) : null}
        {agreement.company_signed_at ? (
          <Button size="sm" variant="outline" onClick={() => onDownload("signed")}>
            <FileDown className="h-3.5 w-3.5" aria-hidden /> Podpisana przez obie strony
          </Button>
        ) : null}
      </div>

      {status === "trainer_signed" ? (
        isCompanySigner ? (
          <div className="space-y-2 rounded-md border border-border p-3">
            <p className="text-sm">
              Trener podpisał umowę. Pobierz wersję trenera, podpisz ją podpisem kwalifikowanym
              i wgraj tutaj.
            </p>
            <input
              ref={signInput}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              aria-label="PDF z podpisem B2B Network"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (file) await onCompanySign(file);
                event.target.value = "";
              }}
            />
            <Button size="sm" disabled={busy} onClick={() => signInput.current?.click()}>
              <Upload className="h-3.5 w-3.5" aria-hidden /> Wgraj PDF z moim podpisem
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Umowa czeka na podpis osoby z listy reprezentantów B2B Network.
          </p>
        )
      ) : null}

      {canGenerate ? (
        <form
          className="space-y-3 rounded-md border border-border p-3"
          onSubmit={async (event) => {
            event.preventDefault();
            await onGenerate({ partner: form, company_email: companyEmail.trim() });
          }}
        >
          <p className="text-sm font-medium">Dane trenera do umowy</p>
          {partnerError ? (
            <p role="alert" className="text-xs text-destructive">
              {partnerError}
            </p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            {PARTNER_FIELDS.map((field) => (
              <FormField
                key={field.key}
                label={field.label}
                htmlFor={`partner-${field.key}`}
                required={field.required}
              >
                <Input
                  id={`partner-${field.key}`}
                  value={form[field.key]}
                  maxLength={field.key === "address" || field.key === "company" ? 300 : 255}
                  onChange={(event) => setForm({ ...form, [field.key]: event.target.value })}
                />
              </FormField>
            ))}
            <FormField
              label="E-mail osoby z B2B Network w umowie"
              htmlFor="partner-company-email"
              required
            >
              <Input
                id="partner-company-email"
                type="email"
                value={companyEmail}
                maxLength={255}
                onChange={(event) => setCompanyEmail(event.target.value)}
              />
            </FormField>
          </div>
          {missing.length > 0 ? (
            <p className="text-xs text-muted-foreground">Brakuje: {missing.join(", ")}.</p>
          ) : null}
          <Button
            type="submit"
            size="sm"
            disabled={busy || missing.length > 0 || companyEmail.trim().length < 3}
          >
            {agreement.generated_at ? "Przygotuj umowę ponownie" : "Przygotuj umowę"}
          </Button>
        </form>
      ) : null}
    </div>
  );
}

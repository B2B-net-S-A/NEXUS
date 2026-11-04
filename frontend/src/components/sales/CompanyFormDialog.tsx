"use client";

import Link from "next/link";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  LIFECYCLE_LABELS,
  TIER_LABELS,
  useCreateSalesCompany,
  useRegistryLookup,
  useUpdateSalesCompany,
  type CompanyInput,
  type CompanyLifecycle,
  type CompanyTier,
  type DuplicateCompany,
  type Ref,
  type SalesCompany,
} from "@/lib/api/sales";

import { CompanyPicker } from "./CompanyPicker";
import { SalesSelect } from "./SalesSelect";
import { useOwnerFilterOptions } from "./useOwnerFilterOptions";

interface CompanyFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edycja istniejącej firmy; brak = nowa. */
  company?: SalesCompany;
  onSaved?: (company: SalesCompany) => void;
}

interface FormState {
  name: string;
  legal_name: string;
  nip: string;
  domain: string;
  industry: string;
  hq_city: string;
  website_url: string;
  linkedin_url: string;
  lifecycle_stage: CompanyLifecycle;
  tier: CompanyTier | "";
  description: string;
  owner: string;
  tags: string;
  parent: Ref | null;
}

function initial(company?: SalesCompany): FormState {
  return {
    name: company?.name ?? "",
    legal_name: company?.legal_name ?? "",
    nip: company?.nip ?? "",
    domain: company?.domain ?? "",
    industry: company?.industry ?? "",
    hq_city: company?.hq_city ?? "",
    website_url: company?.website_url ?? "",
    linkedin_url: company?.linkedin_url ?? "",
    lifecycle_stage: company?.lifecycle_stage ?? "lead",
    tier: company?.tier ?? "",
    description: company?.description ?? "",
    owner: company?.owner ? String(company.owner.id) : "",
    tags: (company?.tags ?? []).join(", "),
    parent: company?.parent ?? null,
  };
}

/** Duplikaty z odpowiedzi 409 (`sales_company_duplicate`), czytane strukturalnie. */
export function duplicatesFromError(error: unknown): DuplicateCompany[] {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)?.response
    ?.data?.detail as { code?: unknown; duplicates?: unknown } | undefined;
  if (detail?.code !== "sales_company_duplicate" || !Array.isArray(detail.duplicates)) {
    return [];
  }
  return detail.duplicates as DuplicateCompany[];
}

const LIFECYCLE_OPTIONS = Object.entries(LIFECYCLE_LABELS).map(([value, label]) => ({
  value,
  label,
}));
const TIER_OPTIONS = Object.entries(TIER_LABELS).map(([value, label]) => ({ value, label }));

/** Nowa firma albo edycja: duplikat (ten sam NIP albo nazwa) ostrzega, nie blokuje. */
export function CompanyFormDialog({ open, onOpenChange, company, onSaved }: CompanyFormDialogProps) {
  const [form, setForm] = useState<FormState>(() => initial(company));
  const [duplicates, setDuplicates] = useState<DuplicateCompany[]>([]);
  const create = useCreateSalesCompany();
  const update = useUpdateSalesCompany(company?.id ?? 0);
  const { showError, showSuccess } = useToast();
  const registry = useRegistryLookup();
  const pending = create.isPending || update.isPending;
  const ownerOptions = useOwnerFilterOptions().filter((option) => option.value.startsWith("acct:"));
  const ownerChoices = [
    ...(company?.owner && !ownerOptions.some((option) => option.value === `acct:${company.owner!.id}`)
      ? [{ value: String(company.owner.id), label: company.owner.name }]
      : []),
    ...ownerOptions.map((option) => ({ value: option.value.slice(5), label: option.label })),
  ];

  const fillFromRegistry = () =>
    registry.mutate(form.nip, {
      onSuccess: (found) => {
        setForm((current) => ({
          ...current,
          name: current.name.trim() ? current.name : (found.name ?? ""),
          legal_name: found.name ?? current.legal_name,
          nip: found.nip ?? current.nip,
          hq_city: current.hq_city.trim() ? current.hq_city : (found.hq_city ?? ""),
        }));
        showSuccess("Uzupełniono dane z rejestru.");
      },
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się pobrać danych z rejestru.")),
    });

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    if (key === "name" || key === "nip") setDuplicates([]);
  };

  const payload = (): CompanyInput => ({
    name: form.name.trim(),
    legal_name: form.legal_name.trim() || null,
    nip: form.nip.trim() || null,
    domain: form.domain.trim() || null,
    industry: form.industry.trim() || null,
    hq_city: form.hq_city.trim() || null,
    website_url: form.website_url.trim() || null,
    linkedin_url: form.linkedin_url.trim() || null,
    lifecycle_stage: form.lifecycle_stage,
    tier: form.tier || null,
    description: form.description.trim() || null,
    tags: form.tags
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean),
    parent_company_id: form.parent?.id ?? null,
    // Opiekuna zmienia obecny opiekun albo admin (API zwraca 403) — wysyłamy tylko zmianę.
    ...(form.owner !== (company?.owner ? String(company.owner.id) : "")
      ? { owner_user_id: form.owner ? Number(form.owner) : null }
      : {}),
  });

  const save = (allowDuplicate: boolean) => {
    if (!form.name.trim()) {
      showError("Podaj nazwę firmy.");
      return;
    }
    const done = (saved: SalesCompany) => {
      showSuccess(company ? "Zapisano zmiany firmy." : "Dodano firmę do kartoteki.");
      onSaved?.(saved);
      onOpenChange(false);
    };
    if (company) {
      update.mutate(payload(), {
        onSuccess: done,
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać firmy.")),
      });
      return;
    }
    create.mutate(
      { ...payload(), allow_duplicate: allowDuplicate },
      {
        onSuccess: done,
        onError: (error) => {
          const found = duplicatesFromError(error);
          if (found.length) {
            setDuplicates(found);
            return;
          }
          showError(apiErrorMessage(error, "Nie udało się dodać firmy."));
        },
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={company ? "Edytuj firmę" : "Nowa firma"}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Anuluj
          </Button>
          {duplicates.length > 0 ? (
            <Button onClick={() => save(true)} loading={pending}>
              Zapisz mimo to
            </Button>
          ) : (
            <Button onClick={() => save(false)} loading={pending}>
              {company ? "Zapisz" : "Dodaj firmę"}
            </Button>
          )}
        </>
      }
    >
      {duplicates.length > 0 && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm"
        >
          <p className="font-medium text-foreground">
            Ta firma jest już w kartotece sprzedaży (ten sam NIP albo nazwa).
          </p>
          <ul className="mt-2 space-y-1">
            {duplicates.map((duplicate) => (
              <li key={duplicate.id}>
                <Link className="text-primary hover:underline" href={`/sales/companies/${duplicate.id}`}>
                  {duplicate.name}
                </Link>
                {duplicate.nip && (
                  <span className="text-muted-foreground"> · NIP {duplicate.nip}</span>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-muted-foreground">
            Otwórz istniejącą albo zapisz mimo to, jeśli to inna spółka o tej samej nazwie.
          </p>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-company-name">Nazwa</Label>
          <Input
            id="sales-company-name"
            value={form.name}
            onChange={(event) => set("name", event.target.value)}
            autoFocus
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-company-nip">NIP</Label>
          <div className="flex gap-2">
            <Input
              id="sales-company-nip"
              className="w-0 flex-1"
              value={form.nip}
              inputMode="numeric"
              onChange={(event) => set("nip", event.target.value)}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              loading={registry.isPending}
              disabled={form.nip.replace(/\D/g, "").length !== 10}
              onClick={fillFromRegistry}
            >
              Pobierz z rejestru
            </Button>
          </div>
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-company-legal">Pełna nazwa prawna</Label>
          <Input
            id="sales-company-legal"
            value={form.legal_name}
            onChange={(event) => set("legal_name", event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-company-lifecycle">Etap relacji</Label>
          <SalesSelect
            id="sales-company-lifecycle"
            value={form.lifecycle_stage}
            onValueChange={(value) => set("lifecycle_stage", value as CompanyLifecycle)}
            options={LIFECYCLE_OPTIONS}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-company-tier">Wielkość</Label>
          <SalesSelect
            id="sales-company-tier"
            value={form.tier}
            onValueChange={(value) => set("tier", value as CompanyTier | "")}
            options={TIER_OPTIONS}
            anyLabel="Nie określono"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-company-industry">Branża</Label>
          <Input
            id="sales-company-industry"
            value={form.industry}
            onChange={(event) => set("industry", event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-company-city">Miasto</Label>
          <Input
            id="sales-company-city"
            value={form.hq_city}
            onChange={(event) => set("hq_city", event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-company-www">Strona www</Label>
          <Input
            id="sales-company-www"
            value={form.website_url}
            onChange={(event) => set("website_url", event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sales-company-linkedin">LinkedIn</Label>
          <Input
            id="sales-company-linkedin"
            value={form.linkedin_url}
            onChange={(event) => set("linkedin_url", event.target.value)}
          />
        </div>
        {company && (
          <div className="space-y-1">
            <Label htmlFor="sales-company-owner">Opiekun</Label>
            <SalesSelect
              id="sales-company-owner"
              value={form.owner}
              onValueChange={(value) => set("owner", value)}
              options={ownerChoices}
              anyLabel={company.owner_label ? `Bez konta (${company.owner_label} z Atlasa)` : "Bez opiekuna"}
            />
          </div>
        )}
        <div className="space-y-1">
          <Label htmlFor="sales-company-parent">Firma matka (grupa)</Label>
          <CompanyPicker id="sales-company-parent" value={form.parent} onChange={(value) => set("parent", value)} />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-company-tags">Tagi (po przecinku)</Label>
          <Input id="sales-company-tags" value={form.tags} onChange={(event) => set("tags", event.target.value)} />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="sales-company-description">Opis</Label>
          <Textarea
            id="sales-company-description"
            rows={3}
            value={form.description}
            onChange={(event) => set("description", event.target.value)}
          />
        </div>
      </div>
    </AppModal>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

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
  useOwnerCandidates,
  usePatchSalesCompany,
  useRegistryLookup,
  useSalesCompanies,
  useUpdateSalesCompany,
  type CompanyInput,
  type CompanyLifecycle,
  type CompanyTier,
  type DuplicateCompany,
  type Ref,
  type RegistryCompany,
  type SalesCompany,
} from "@/lib/api/sales";
import { useCompanyIdentity } from "@/lib/api/sales-handoffs";
import { formatNip } from "@/lib/nip";
import { useDebouncedValue } from "@/lib/use-debounced-value";

import { CompanyPicker } from "./CompanyPicker";
import { CompanyIdentityHints } from "./handoff/CompanyIdentityHints";
import { SalesSelect } from "./SalesSelect";
import { useOwnerFilterOptions } from "./useOwnerFilterOptions";

interface CompanyFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edycja istniejącej firmy; brak = nowa. */
  company?: SalesCompany;
  onSaved?: (company: SalesCompany) => void;
  /** Z palety ⌘K: nowa firma z tym NIP-em, dane z rejestru pobierane od razu. */
  initialNip?: string;
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

// Rejestry podają nazwę z pełną formą prawną („CD PROJEKT RED SPÓŁKA AKCYJNA”), a karty
// w kartotece mają nazwę handlową. Bez formy nazwa trafia w istniejącą kartę bez NIP-u.
const LEGAL_FORM =
  /[\s,]+(SPÓŁKA (Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ|AKCYJNA|KOMANDYTOWO-AKCYJNA|KOMANDYTOWA|JAWNA|PARTNERSKA)|SP\. Z O\.\s?O\.|S\.A\.|SP\. K\.|SP\. J\.)$/i;

export function nameWithoutLegalForm(name: string): string {
  return name.trim().replace(LEGAL_FORM, "").trim();
}

function initial(company?: SalesCompany, nip?: string): FormState {
  return {
    name: company?.name ?? "",
    legal_name: company?.legal_name ?? "",
    nip: company?.nip ?? nip ?? "",
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
export function CompanyFormDialog({
  open,
  onOpenChange,
  company,
  onSaved,
  initialNip,
}: CompanyFormDialogProps) {
  const [form, setForm] = useState<FormState>(() => initial(company, initialNip));
  const [fromRegistry, setFromRegistry] = useState<RegistryCompany | null>(null);
  const patchExisting = usePatchSalesCompany();
  const [duplicates, setDuplicates] = useState<DuplicateCompany[]>([]);
  const create = useCreateSalesCompany();
  const update = useUpdateSalesCompany(company?.id ?? 0);
  const { showError, showSuccess } = useToast();
  const registry = useRegistryLookup();
  const pending = create.isPending || update.isPending;
  // Tożsamość firmy (10.11.2026): przy nowej karcie podpowiadamy istniejące karty i mówimy,
  // jaką domenę serwer weźmie z adresu strony. To podpowiedź: zapis od niej nie zależy,
  // a przy edycji pole domeny idzie do zapisu dokładnie tak, jak je zostawiono.
  const typedName = useDebouncedValue(form.name, 300);
  const typedWebsite = useDebouncedValue(form.website_url, 300);
  const identity = useCompanyIdentity({ name: typedName, website: typedWebsite }, open && !company);
  const suggestedDomain = company || form.domain.trim() ? null : (identity.data?.domain ?? null);
  const candidates = useOwnerCandidates(open && Boolean(company));
  const ownerOptions = new Map<string, string>(
    useOwnerFilterOptions()
      .filter((option) => option.value.startsWith("acct:"))
      .map((option) => [option.value.slice(5), option.label]),
  );
  // Katalog obejmuje też osoby bez otwartych szans w domyślnym lejku.
  for (const candidate of candidates.data ?? []) {
    const id = String(candidate.id);
    if (!ownerOptions.has(id)) ownerOptions.set(id, candidate.name);
  }
  const currentOwner = company?.owner;
  const ownerChoices = [
    ...(currentOwner && !ownerOptions.has(String(currentOwner.id))
      ? [{ value: String(currentOwner.id), label: currentOwner.name }]
      : []),
    ...Array.from(ownerOptions, ([value, label]) => ({ value, label })),
  ];

  const fillFromRegistry = (nip: string = form.nip) =>
    registry.mutate(nip, {
      onSuccess: (found) => {
        setFromRegistry(found);
        setForm((current) => ({
          ...current,
          name: current.name.trim() ? current.name : nameWithoutLegalForm(found.name ?? ""),
          legal_name: found.name ?? current.legal_name,
          nip: found.nip ?? current.nip,
          hq_city: current.hq_city.trim() ? current.hq_city : (found.hq_city ?? ""),
        }));
        showSuccess("Uzupełniono dane z rejestru.");
      },
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się pobrać danych z rejestru.")),
    });

  const askedRegistry = useRef(false);
  useEffect(() => {
    if (!open || company || !initialNip || askedRegistry.current) return;
    askedRegistry.current = true;
    fillFromRegistry(initialNip);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- jedno zapytanie na otwarcie z palety
  }, [open, company, initialNip]);

  // Okno z NIP-em z palety albo z przycisku Jarvisa: najpierw karta, która już ma ten NIP.
  const byNip = useSalesCompanies({ q: initialNip ?? "" }, open && !company && Boolean(initialNip));
  const nipTaken = (byNip.data?.items ?? []).filter((item) => item.nip === initialNip);
  // NIP wolny: karta o tej samej nazwie to najpewniej ta firma bez NIP-u — zamiast drugiej
  // karty dopisujemy NIP do istniejącej.
  const sameName =
    initialNip && fromRegistry && byNip.isSuccess && nipTaken.length === 0
      ? (identity.data?.matches ?? []).filter(
          // Tylko karta, o której wiemy, że nie ma NIP-u — numer innej spółki tej samej
          // marki zostaje nietknięty.
          (match) => match.reason === "name" && match.nip === null,
        )
      : [];
  const fillExisting = (id: number) =>
    patchExisting.mutate(
      // Sam NIP: resztę pól z rejestru dopisze sprawdzenie po zapisie NIP-u, które nie
      // nadpisuje pól wpisanych przez człowieka (dane-firm-z-rejestrow.md).
      { id, payload: { nip: form.nip.trim() || null } },
      {
        onSuccess: (saved) => {
          showSuccess(`Dopisano NIP do karty ${saved.name}.`);
          onSaved?.(saved);
          onOpenChange(false);
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się dopisać NIP-u do karty.")),
      },
    );

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    if (key === "name" || key === "nip") setDuplicates([]);
    if (key === "nip") setFromRegistry(null);
  };

  const payload = (): CompanyInput => ({
    name: form.name.trim(),
    legal_name: form.legal_name.trim() || null,
    nip: form.nip.trim() || null,
    // KRS i REGON z rejestru tylko przy nowej karcie i NIP-ie, dla którego je pobrano.
    ...(!company && fromRegistry ? { krs: fromRegistry.krs, regon: fromRegistry.regon } : {}),
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
          ) : sameName.length > 0 ? (
            <Button variant="outline" onClick={() => save(true)} loading={pending}>
              To inna spółka — dodaj nową kartę
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
      {initialNip && registry.isPending && (
        <p className="mb-3 text-sm text-muted-foreground">
          Sprawdzam NIP {formatNip(initialNip)} w rejestrach (biała lista VAT, KRS)…
        </p>
      )}
      {fromRegistry && (
        <p className="mb-3 text-xs text-muted-foreground" data-testid="registry-summary">
          Z rejestru: {fromRegistry.name}
          {fromRegistry.krs && ` · KRS ${fromRegistry.krs}`}
          {fromRegistry.regon && ` · REGON ${fromRegistry.regon}`}
          {fromRegistry.address && ` · ${fromRegistry.address}`}
        </p>
      )}
      {nipTaken.length > 0 && duplicates.length === 0 && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm"
          data-testid="registry-nip-taken"
        >
          <p className="font-medium text-foreground">
            NIP {formatNip(initialNip ?? "")} ma już karta w kartotece sprzedaży:
          </p>
          <ul className="mt-2 space-y-1">
            {nipTaken.map((item) => (
              <li key={item.id}>
                <Link className="text-primary hover:underline" href={`/sales/companies/${item.id}`}>
                  {item.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {sameName.length > 0 && duplicates.length === 0 && (
        <div
          role="status"
          className="mb-4 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm"
          data-testid="registry-same-name"
        >
          <p className="font-medium text-foreground">
            W kartotece jest już karta o tej nazwie, bez NIP-u {formatNip(form.nip.replace(/\D/g, ""))}.
          </p>
          <ul className="mt-2 space-y-2">
            {sameName.map((match) => (
              <li key={match.id} className="flex flex-wrap items-center gap-2">
                <Link className="font-medium text-primary hover:underline" href={`/sales/companies/${match.id}`}>
                  {match.name}
                </Link>
                <span className="text-muted-foreground">
                  {[match.hq_city, match.domain, match.open_opportunities ? `otwarte szanse: ${match.open_opportunities}` : null]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                <Button
                  size="sm"
                  className="ml-auto"
                  loading={patchExisting.isPending}
                  onClick={() => fillExisting(match.id)}
                >
                  Dopisz NIP do tej karty
                </Button>
              </li>
            ))}
          </ul>
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
          {!company && duplicates.length === 0 && sameName.length === 0 && <CompanyIdentityHints matches={identity.data?.matches ?? []} />}
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
              onClick={() => fillFromRegistry()}
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
          <Label htmlFor="sales-company-domain">Domena poczty</Label>
          <Input
            id="sales-company-domain"
            value={form.domain}
            placeholder={suggestedDomain ?? "np. firma.pl"}
            onChange={(event) => set("domain", event.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            {suggestedDomain
              ? `Zapiszemy ${suggestedDomain} z adresu strony. Po domenie NEXUS dopasowuje pocztę i spotkania.`
              : "Po domenie NEXUS dopasowuje do firmy pocztę i spotkania."}
          </p>
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

"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  type KnowledgeReference,
  type KnowledgeReferenceIn,
  type ReferenceKind,
  toReferenceIn,
  useKnowledge,
  useParseReferenceTable,
  useSaveKnowledge,
} from "@/lib/api/sales-potential";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { SalesSelect } from "../SalesSelect";
import { KIND_LABEL } from "./potential-format";

// Sprzedaż → Leady → Boty → Baza wiedzy (decyzja Artura 23.11.2026): co ocena
// potencjału wie o nas. Edytuje każdy z „Sprzedaż: edycja”; treść nie trafia do repo.

const KIND_OPTIONS = (Object.keys(KIND_LABEL) as ReferenceKind[]).map((value) => ({
  value,
  label: KIND_LABEL[value],
}));
const KIND_VARIANT = { list: "success", realizacja: "info", logo: "neutral" } as const;

const EMPTY: KnowledgeReferenceIn = {
  id: "",
  client: "",
  kind: "list",
  sectors: [],
  services: [],
  scope: "",
  since: "",
  letter_date: null,
  valid_until: null,
  signed_by: "",
  quote: "",
  public_tender: false,
  note: "",
};

/** Uwaga przy referencji: nieaktualny list albo brak klienta w NEXUSIE. */
export function referenceWarning(ref: KnowledgeReference): string | null {
  if (ref.fresh === false) return "List starszy niż rok albo po terminie ważności";
  if (ref.kind !== "list") return null;
  if (ref.nexus_active === null) return "Nie znalazłem klienta o tej nazwie w NEXUSIE";
  if (ref.nexus_active === 0) return "Klient bez aktywnych kontraktów w NEXUSIE";
  return null;
}

function splitTags(text: string): string[] {
  return text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function ReferenceDialog({
  initial,
  onClose,
  onSave,
  saving,
}: {
  initial: KnowledgeReferenceIn;
  onClose: () => void;
  onSave: (ref: KnowledgeReferenceIn) => void;
  saving: boolean;
}) {
  const [ref, setRef] = useState(initial);
  const [sectors, setSectors] = useState(initial.sectors.join(", "));
  const [services, setServices] = useState(initial.services.join(", "));
  const set = <K extends keyof KnowledgeReferenceIn>(key: K, value: KnowledgeReferenceIn[K]) =>
    setRef((current) => ({ ...current, [key]: value }));
  const submit = () =>
    onSave({ ...ref, client: ref.client.trim(), sectors: splitTags(sectors), services: splitTags(services) });
  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={initial.client ? `Referencja: ${initial.client}` : "Nowa referencja"}
      description="Ocena potencjału pokazuje zakres dokładnie tak, jak tu zapiszesz. Podpis i notatka zostają w NEXUSIE."
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={!ref.client.trim()} loading={saving}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="ref-client">Klient</Label>
          <Input id="ref-client" value={ref.client} onChange={(e) => set("client", e.target.value)} maxLength={120} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ref-kind">Typ</Label>
          <SalesSelect id="ref-kind" value={ref.kind} onValueChange={(value) => set("kind", value as ReferenceKind)} options={KIND_OPTIONS} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ref-sectors">Branże (po przecinku)</Label>
          <Input id="ref-sectors" value={sectors} onChange={(e) => setSectors(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ref-services">Usługi (po przecinku)</Label>
          <Input id="ref-services" value={services} onChange={(e) => setServices(e.target.value)} />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="ref-scope">Zakres</Label>
          <Textarea id="ref-scope" rows={3} value={ref.scope} onChange={(e) => set("scope", e.target.value)} maxLength={600} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ref-since">Współpraca od</Label>
          <Input id="ref-since" value={ref.since} onChange={(e) => set("since", e.target.value)} maxLength={60} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ref-signed">Podpisał (stanowisko)</Label>
          <Input id="ref-signed" value={ref.signed_by} onChange={(e) => set("signed_by", e.target.value)} maxLength={160} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ref-letter">Data listu</Label>
          <Input id="ref-letter" type="date" value={ref.letter_date ?? ""} onChange={(e) => set("letter_date", e.target.value || null)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ref-valid">Ważny do</Label>
          <Input id="ref-valid" type="date" value={ref.valid_until ?? ""} onChange={(e) => set("valid_until", e.target.value || null)} />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="ref-quote">Cytat z listu</Label>
          <Textarea id="ref-quote" rows={2} value={ref.quote} onChange={(e) => set("quote", e.target.value)} maxLength={400} />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="ref-note">Notatka (tylko dla nas)</Label>
          <Input id="ref-note" value={ref.note} onChange={(e) => set("note", e.target.value)} maxLength={300} />
        </div>
        <label className="flex items-center gap-2 text-sm text-foreground sm:col-span-2" htmlFor="ref-tender">
          <input
            id="ref-tender"
            type="checkbox"
            className="h-4 w-4 accent-[hsl(var(--primary))]"
            checked={ref.public_tender}
            onChange={(e) => set("public_tender", e.target.checked)}
          />
          Wolno ją wskazać w przetargu publicznym
        </label>
      </div>
    </AppModal>
  );
}

function ImportDialog({
  onClose,
  onAdd,
  saving,
}: {
  onClose: () => void;
  onAdd: (refs: KnowledgeReference[]) => void;
  saving: boolean;
}) {
  const parse = useParseReferenceTable();
  const { showError } = useToast();
  const [text, setText] = useState("");
  const preview = parse.data;
  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Wklej tabelę referencji"
      description="Tabela z dokumentu w formacie Markdown: | Klient | Sektor | Zakres | Współpraca od | Podpisał | Data listu |. „(ważny 12 mies.)” przy dacie ustawia datę ważności."
      size="xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            variant="outline"
            disabled={!text.trim()}
            loading={parse.isPending}
            onClick={() =>
              parse.mutate(text, { onError: (error) => showError(apiErrorMessage(error, "Nie udało się odczytać tabeli.")) })
            }
          >
            Podgląd
          </Button>
          <Button disabled={!preview?.length} loading={saving} onClick={() => preview && onAdd(preview)}>
            {preview?.length ? `Dodaj ${preview.length}` : "Dodaj"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Textarea
          aria-label="Tabela referencji"
          rows={8}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="font-mono text-xs"
        />
        {preview && (
          <p className="text-sm text-foreground">
            {preview.length === 0
              ? "Nie znalazłem wierszy z klientem. Sprawdź, czy tabela ma nagłówek z kolumną „Klient”."
              : `Rozpoznane: ${preview.map((ref) => ref.client).join(", ")}`}
          </p>
        )}
      </div>
    </AppModal>
  );
}

/** Ekran bazy wiedzy oceny potencjału. */
export function KnowledgeBaseView() {
  const query = useKnowledge();
  const save = useSaveKnowledge();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [offer, setOffer] = useState("");
  const [editing, setEditing] = useState<KnowledgeReferenceIn | null>(null);
  const [importing, setImporting] = useState(false);
  const data = query.data;
  useEffect(() => {
    if (data) setOffer(data.offer);
  }, [data]);

  const state = resolveViewState({ isLoading: query.isLoading, error: query.error, isSuccess: query.isSuccess });
  if (state === "loading") return <p className="py-6 text-sm text-muted-foreground">Wczytywanie bazy wiedzy…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  if (!data) return null;

  const canEdit = data.can_edit;
  const references = data.references.map(toReferenceIn);
  const persist = (next: { offer?: string; references?: KnowledgeReferenceIn[] }, done: string, after?: () => void) =>
    save.mutate(
      { offer: next.offer ?? data.offer, references: next.references ?? references },
      {
        onSuccess: () => {
          showSuccess(done);
          after?.();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać bazy wiedzy.")),
      },
    );
  const upsert = (ref: KnowledgeReferenceIn) =>
    persist(
      {
        references: ref.id
          ? references.map((item) => (item.id === ref.id ? ref : item))
          : [...references, ref],
      },
      "Zapisano referencję.",
      () => setEditing(null),
    );
  const remove = async (ref: KnowledgeReference) => {
    const ok = await askConfirm({
      title: `Usunąć referencję ${ref.client}?`,
      description: "Ocena potencjału przestanie ją proponować. Zmiana zostaje w historii bazy.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (ok) persist({ references: references.filter((item) => item.id !== ref.id) }, "Usunięto referencję.");
  };
  const last = data.history[0];

  return (
    <div className="space-y-4">
      <Card className="space-y-2 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-foreground">Baza wiedzy do oceny potencjału</h2>
            <p className="text-xs text-muted-foreground">
              Ocena bierze stąd opis oferty i referencje; zakres referencji pokazuje dokładnie tak, jak tu jest.
              {last ? ` Ostatnia zmiana: ${formatIsoDatePl(last.at)}, ${last.by_name} (${last.summary}).` : ""}
            </p>
          </div>
          {canEdit && (
            <div className="flex shrink-0 gap-2">
              <Button size="sm" variant="outline" onClick={() => setImporting(true)}>
                Wklej tabelę
              </Button>
              <Button size="sm" onClick={() => setEditing({ ...EMPTY })}>
                Dodaj referencję
              </Button>
            </div>
          )}
        </div>
      </Card>
        <Card className="space-y-2 p-4">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-foreground">Referencje ({data.references.length})</h3>
            <span className="text-xs text-muted-foreground">„W NEXUSIE” = aktywne kontrakty klienta</span>
          </div>
          {data.references.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Baza nie ma jeszcze referencji. Wklej tabelę z dokumentu albo dodaj je pojedynczo.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-1 pr-2 font-normal">Klient</th>
                    <th className="py-1 pr-2 font-normal">Typ</th>
                    <th className="whitespace-nowrap py-1 pr-2 font-normal">List z</th>
                    <th className="whitespace-nowrap py-1 pr-2 font-normal">W NEXUSIE</th>
                    <th className="py-1 pr-2 font-normal">Uwaga</th>
                    {canEdit && <th className="py-1 font-normal" aria-label="Akcje" />}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.references.map((ref) => {
                    const warning = referenceWarning(ref);
                    return (
                      <tr key={ref.id} className="align-top">
                        <td className="py-1.5 pr-2 text-foreground">
                          <span className="flex items-center gap-1.5">
                            <span
                              aria-hidden
                              className={cn("size-1.5 shrink-0 rounded-full", warning ? "bg-warning" : "bg-success")}
                            />
                            {ref.client}
                          </span>
                          {ref.scope && <span className="block max-w-[28rem] truncate text-muted-foreground" title={ref.scope}>{ref.scope}</span>}
                        </td>
                        <td className="py-1.5 pr-2">
                          <Badge variant={KIND_VARIANT[ref.kind]} size="sm">
                            {ref.kind}
                          </Badge>
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">
                          {ref.letter_date ? formatIsoDatePl(ref.letter_date) : "—"}
                          {ref.valid_until && <span className="block">do {formatIsoDatePl(ref.valid_until)}</span>}
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums text-foreground">
                          {ref.nexus_active === null || ref.nexus_active === undefined ? "—" : ref.nexus_active}
                        </td>
                        <td className="py-1.5 pr-2 text-muted-foreground">{warning ?? ""}</td>
                        {canEdit && (
                          <td className="whitespace-nowrap py-1.5 text-right">
                            <Button size="sm" variant="quiet" onClick={() => setEditing(toReferenceIn(ref))}>
                              Edytuj
                            </Button>
                            <Button size="sm" variant="quiet" onClick={() => void remove(ref)}>
                              Usuń
                            </Button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card className="space-y-2 p-4">
          <Label htmlFor="kb-offer" className="text-sm font-semibold text-foreground">
            O nas i oferta
          </Label>
          <p className="text-xs text-muted-foreground">
            Dane firmy, ścieżki współpracy, gwarancje, przykłady wdrożeń bez nazw klientów. Model nie dopisze nic spoza tego tekstu.
          </p>
          <Textarea
            id="kb-offer"
            rows={16}
            value={offer}
            onChange={(e) => setOffer(e.target.value)}
            readOnly={!canEdit}
            maxLength={30000}
            className="text-xs"
          />
          {canEdit && (
            <Button
              size="sm"
              className="w-fit"
              disabled={offer === data.offer}
              loading={save.isPending && !editing}
              onClick={() => persist({ offer }, "Zapisano opis oferty.")}
            >
              Zapisz opis
            </Button>
          )}
        </Card>
      {editing && (
        <ReferenceDialog initial={editing} onClose={() => setEditing(null)} onSave={upsert} saving={save.isPending} />
      )}
      {importing && (
        <ImportDialog
          onClose={() => setImporting(false)}
          saving={save.isPending}
          onAdd={(refs) =>
            persist(
              { references: [...references, ...refs.map(toReferenceIn)] },
              `Dodano ${refs.length} referencji.`,
              () => setImporting(false),
            )
          }
        />
      )}
      {confirmDialog}
    </div>
  );
}

"use client";

import { useState, type ReactNode } from "react";
import { Mail } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { PROVIDER_LABELS } from "@/components/equipment/equipment-format";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useClientPack,
  useClientPackPreview,
  useSaveClientPack,
  type ClientPack,
} from "@/lib/api/client-onboarding";
import type { EquipmentProvider, ProtocolKind } from "@/lib/api/equipment";
import { resolveViewState } from "@/lib/view-state";

import { PackItemsEditor } from "./PackItemsEditor";
import {
  draftFromPack,
  draftProblem,
  isDirty,
  saveFromDraft,
  type PackDraft,
} from "./onboarding-pack-format";

const STANDARD = "standard";
const NOBODY = "none";

function Card({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-3" aria-label={title}>
      <div className="flex items-center gap-2">
        <h3 className="text-[13px] font-semibold text-foreground">{title}</h3>
        {aside ? <div className="ml-auto">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

function TemplateSelect({
  kind,
  pack,
  value,
  onChange,
  readOnly,
}: {
  kind: ProtocolKind;
  pack: ClientPack;
  value: number | null;
  onChange: (value: number | null) => void;
  readOnly: boolean;
}) {
  const options = pack.options.templates.filter((template) => template.kind === kind);
  const label = kind === "wydanie" ? "Wzór protokołu wydania" : "Wzór protokołu zwrotu";
  const selected = options.find((template) => template.id === value);
  if (readOnly) {
    return (
      <FormField label={label}>
        <p className="text-sm">{selected ? selected.name : "Standard recepcji"}</p>
      </FormField>
    );
  }
  const id = `pack-template-${kind}`;
  return (
    <FormField label={label} htmlFor={id}>
      <Select
        value={value === null ? STANDARD : String(value)}
        onValueChange={(next) => onChange(next === STANDARD ? null : Number(next))}
      >
        <SelectTrigger id={id} className="h-8 text-sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={STANDARD}>Standard recepcji</SelectItem>
          {options.map((template) => (
            <SelectItem key={template.id} value={String(template.id)}>
              {template.name}
              {template.is_active ? "" : " (wycofany)"}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

function PreviewDialog({ clientId, onClose }: { clientId: number; onClose: () => void }) {
  const preview = useClientPackPreview(clientId, true);
  const state = resolveViewState({
    isLoading: preview.isLoading,
    error: preview.error,
    isSuccess: preview.isSuccess,
  });
  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Podgląd maila powitalnego"
      description="Tak wygląda mail z zapisanego pakietu. Imię, dzień startu i opiekuna uzupełnia kontrakt; mail wysyła opiekun z zakładki „Wejście” kontraktu."
      size="lg"
      footer={
        <Button variant="ghost" onClick={onClose}>
          Zamknij
        </Button>
      }
    >
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Składanie podglądu…</p>
      ) : state === "ready" && preview.data ? (
        <div className="space-y-2">
          <p className="text-sm">
            <span className="text-muted-foreground">Temat: </span>
            {preview.data.subject}
          </p>
          <div className="max-h-[50dvh] overflow-y-auto whitespace-pre-line rounded-md border border-border bg-muted/40 p-3 text-sm">
            {preview.data.body}
          </div>
        </div>
      ) : (
        <QueryStateNotice
          state={state === "ready" ? "error" : (state as "forbidden" | "not_found" | "error")}
          onRetry={() => void preview.refetch()}
        />
      )}
    </AppModal>
  );
}

/**
 * Zakładka klienta „Wejście u klienta” (makieta M5): sprzęt, pierwszy dzień,
 * dokumenty od konsultanta i dostępy. Pakiet dokłada się do ścieżki
 * „Konsultant u klienta” przy każdym nowym kontrakcie klienta.
 */
export function OnboardingPackTab({ clientId }: { clientId: number }) {
  const query = useClientPack(clientId);
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie pakietu…</p>;
  }
  if (state !== "ready" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "ready" || state === "empty" ? "not_found" : state}
        description={
          state === "forbidden"
            ? "Pakiet klienta widzą osoby z podglądem Delivery (Delivery Lead u swoich klientów) i recepcja."
            : undefined
        }
        onRetry={() => void query.refetch()}
      />
    );
  }
  return <PackEditor key={clientId} clientId={clientId} pack={query.data} />;
}

function PackEditor({ clientId, pack }: { clientId: number; pack: ClientPack }) {
  const { showToast } = useToast();
  const save = useSaveClientPack(clientId);
  const [error, setError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  // Szkic liczy się od wersji, którą osoba zaczęła edytować — zapis wysyła ją
  // jako `expected_version` (także 0 dla nowego pakietu), więc cudza zmiana
  // w międzyczasie daje 409, a nie ciche nadpisanie. Flaga sprzętu idzie tylko
  // przy zmianie, z wartością z początku edycji (`saved.provider`).
  const [base, setBase] = useState(() => ({ version: pack.version, draft: draftFromPack(pack) }));
  const [draft, setDraft] = useState<PackDraft>(base.draft);
  const saved = base.draft;
  const outdated = pack.version !== base.version;
  const restart = (next: ClientPack) => {
    const fresh = draftFromPack(next);
    setBase({ version: next.version, draft: fresh });
    setDraft(fresh);
    setError(null);
  };

  const canEdit = pack.can_edit;
  const anyEdit = canEdit.equipment || canEdit.rest;
  const dirty = isDirty(saved, draft, canEdit);
  const set = (patch: Partial<PackDraft>) => setDraft({ ...draft, ...patch });
  const setFirstDay = (patch: Partial<PackDraft["firstDay"]>) =>
    setDraft({ ...draft, firstDay: { ...draft.firstDay, ...patch } });

  const submit = () => {
    const problem = draftProblem(draft);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    save.mutate(saveFromDraft(draft, canEdit, base.version, saved.provider), {
      onSuccess: (next) => {
        restart(next);
        showToast("Pakiet zapisany", "success");
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać pakietu.")),
    });
  };

  const contactName = pack.options.contacts.find((c) => c.id === draft.firstDay.contactId)?.name;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          Pakiet dokłada się do ścieżki „Konsultant u klienta” przy każdym nowym kontrakcie tego
          klienta
          {pack.live_contracts > 0
            ? ` · dotyczy ${pack.live_contracts} ${pack.live_contracts === 1 ? "kontraktu" : "kontraktów"} przed startem i w trakcie`
            : ""}
          .
          {pack.updated_by_name ? ` Ostatnia zmiana: ${pack.updated_by_name}.` : ""}
        </p>
        <Button variant="outline" onClick={() => setPreviewing(true)} disabled={!pack.exists}>
          <Mail className="h-4 w-4" aria-hidden />
          Podgląd maila powitalnego
        </Button>
        {anyEdit ? (
          <Button onClick={submit} disabled={!dirty || save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz pakiet"}
          </Button>
        ) : null}
      </div>
      {outdated ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          <span className="min-w-0 flex-1">
            Ktoś zapisał nowszą wersję pakietu w trakcie Twojej edycji.
          </span>
          <Button variant="outline" size="sm" onClick={() => restart(pack)}>
            Wczytaj nowszą wersję
          </Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {!canEdit.rest && canEdit.equipment ? (
        <p className="text-xs text-muted-foreground">
          Z uprawnieniem „Sprzęt” zmieniasz część sprzętową. Pierwszy dzień, dokumenty i dostępy
          zmienia Delivery Lead klienta albo osoba z „Klienci: dodawanie i edycja”.
        </p>
      ) : null}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2">
        <Card
          title="Sprzęt"
          aside={
            canEdit.equipment ? (
              <Select
                value={draft.provider}
                onValueChange={(value) => set({ provider: value as EquipmentProvider })}
              >
                <SelectTrigger aria-label="Kto daje sprzęt konsultantom" className="h-7 w-40 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(PROVIDER_LABELS) as EquipmentProvider[]).map((value) => (
                    <SelectItem key={value} value={value}>
                      {PROVIDER_LABELS[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <span className="text-xs text-muted-foreground">{PROVIDER_LABELS[draft.provider]}</span>
            )
          }
        >
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Od nas</p>
            <PackItemsEditor
              kind="thing"
              label="Sprzęt od nas"
              items={draft.ours}
              onChange={(ours) => set({ ours })}
              readOnly={!canEdit.equipment}
              addLabel="Dodaj rzecz od nas"
              namePlaceholder="np. laptop 14 cali"
              notePlaceholder="uwagi (klasa, akcesoria)"
              emptyText="Nic od nas."
            />
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Od klienta</p>
            <PackItemsEditor
              kind="thing"
              label="Sprzęt od klienta"
              items={draft.client}
              onChange={(client) => set({ client })}
              readOnly={!canEdit.equipment}
              addLabel="Dodaj rzecz od klienta"
              namePlaceholder="np. karta wejściowa do biura"
              notePlaceholder="gdzie odebrać"
              emptyText="Nic od klienta."
            />
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <TemplateSelect
              kind="wydanie"
              pack={pack}
              value={draft.issueTemplateId}
              onChange={(issueTemplateId) => set({ issueTemplateId })}
              readOnly={!canEdit.equipment}
            />
            <TemplateSelect
              kind="zwrot"
              pack={pack}
              value={draft.returnTemplateId}
              onChange={(returnTemplateId) => set({ returnTemplateId })}
              readOnly={!canEdit.equipment}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Wzory dodaje recepcja z pliku Word z polami (Sprzęt → Wzory protokołów). Protokół
            wydania i zwrotu konsultanta tego klienta powstaje z wybranego wzoru.
          </p>
        </Card>

        <Card title="Pierwszy dzień">
          <FormField
            label="Kto odbiera konsultanta u klienta"
            htmlFor="pack-first-contact"
            description="Domyślnie menedżer z kontraktu — osoba, pod którą konsultant będzie pracował. Ta osoba jest zapasowa, gdy kontrakt nie ma menedżera."
          >
            {canEdit.rest ? (
              <Select
                value={draft.firstDay.contactId === null ? NOBODY : String(draft.firstDay.contactId)}
                onValueChange={(value) =>
                  setFirstDay({ contactId: value === NOBODY ? null : Number(value) })
                }
              >
                <SelectTrigger id="pack-first-contact" className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NOBODY}>tylko menedżer z kontraktu</SelectItem>
                  {pack.options.contacts.map((contact) => (
                    <SelectItem key={contact.id} value={String(contact.id)}>
                      zapasowo: {contact.name}
                      {contact.position ? ` · ${contact.position}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="text-sm">
                menedżer z kontraktu{contactName ? ` · zapasowo: ${contactName}` : ""}
              </p>
            )}
          </FormField>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_6rem]">
            <FormField label="Gdzie" htmlFor="pack-first-place">
              <Input
                id="pack-first-place"
                className="h-8"
                placeholder="adres, piętro, recepcja"
                maxLength={300}
                readOnly={!canEdit.rest}
                value={draft.firstDay.place}
                onChange={(event) => setFirstDay({ place: event.target.value })}
              />
            </FormField>
            <FormField label="O której" htmlFor="pack-first-time">
              <Input
                id="pack-first-time"
                className="h-8 tabular-nums"
                placeholder="9:00"
                maxLength={5}
                readOnly={!canEdit.rest}
                value={draft.firstDay.time}
                onChange={(event) => setFirstDay({ time: event.target.value })}
              />
            </FormField>
          </div>
          <FormField label="Co zabrać" htmlFor="pack-first-bring">
            <Input
              id="pack-first-bring"
              className="h-8"
              placeholder="np. dowód osobisty"
              maxLength={500}
              readOnly={!canEdit.rest}
              value={draft.firstDay.bring}
              onChange={(event) => setFirstDay({ bring: event.target.value })}
            />
          </FormField>
        </Card>

        <Card title="Dokumenty od konsultanta">
          <PackItemsEditor
            kind="document"
            label="Dokumenty od konsultanta"
            items={draft.documents}
            onChange={(documents) => set({ documents })}
            readOnly={!canEdit.rest}
            addLabel="Dodaj dokument"
            namePlaceholder="np. zaświadczenie o niekaralności"
            notePlaceholder="uwagi (np. nie starsze niż 3 miesiące)"
            emptyText="Klient nie wymaga dokumentów."
          />
          <p className="text-xs text-muted-foreground">
            Konsultant nie ma konta, więc dokumenty odhacza opiekun. Lista trafia do maila
            powitalnego.
          </p>
        </Card>

        <Card title="Dostępy">
          <PackItemsEditor
            kind="access"
            label="Dostępy"
            items={draft.accesses}
            onChange={(accesses) => set({ accesses })}
            readOnly={!canEdit.rest}
            assignees={pack.options.assignees}
            addLabel="Dodaj dostęp"
            namePlaceholder="np. konto w domenie klienta, VPN"
            notePlaceholder="kto zakłada (np. klient)"
            emptyText="Bez dostępów do pilnowania."
          />
        </Card>
      </div>
      {previewing ? <PreviewDialog clientId={clientId} onClose={() => setPreviewing(false)} /> : null}
    </div>
  );
}

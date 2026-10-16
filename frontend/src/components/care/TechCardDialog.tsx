"use client";

import { useCallback, useState } from "react";
import { Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CARD_STATUS_LABELS,
  HIRING_SOURCE_LABELS,
  INITIATIVE_KIND_LABELS,
  monthEnd,
  monthOf,
  searchSkills,
  searchVendors,
  useClientAreas,
  useSaveTechCard,
  type CardStatus,
  type HiringSource,
  type Initiative,
  type InitiativeKind,
  type TechCard,
  type TechCardPayload,
} from "@/lib/api/care";
import { warsawToday } from "@/lib/warsaw-date";

import { splitNames } from "./care-format";
import { TokenPicker, type PickedToken } from "./TokenPicker";

const NONE = "none";
const NEW_AREA = "new";

export interface CardFormState {
  interviewOn: string;
  status: CardStatus | typeof NONE;
  satisfaction: string;
  areaId: string;
  newArea: string;
  skills: PickedToken[];
  vendors: PickedToken[];
  hiring: boolean;
  hiringSource: HiringSource | typeof NONE;
  hiringRoles: string;
  projectEndMonth: string;
  projectEndUnknown: boolean;
  teamSize: string;
  teamExternals: string;
  initiatives: Initiative[];
  quote: string;
  note: string;
}

export function initialCardForm(card: TechCard | null, today: string): CardFormState {
  return {
    interviewOn: card?.interview_on ?? today,
    status: card?.status ?? NONE,
    satisfaction: card?.satisfaction ? String(card.satisfaction) : NONE,
    areaId: card?.area ? String(card.area.id) : NONE,
    newArea: "",
    skills: [
      ...(card?.skills ?? []).map((skill) => ({ id: skill.id, name: skill.name })),
      ...(card?.unrecognized_skills ?? []).map((name) => ({ id: null, name })),
    ],
    vendors: (card?.vendors ?? []).map((vendor) => ({ id: vendor.id, name: vendor.name })),
    hiring: card?.hiring === true,
    hiringSource: card?.hiring_source ?? NONE,
    hiringRoles: (card?.hiring_roles ?? []).join(", "),
    projectEndMonth: monthOf(card?.project_end_on),
    projectEndUnknown: card?.project_end_unknown ?? false,
    teamSize: card?.team_size ?? "",
    teamExternals: card?.team_externals != null ? String(card.team_externals) : "",
    initiatives: card?.initiatives ?? [],
    quote: card?.memorable_quote ?? "",
    note: card?.note ?? "",
  };
}

/** Formularz → ciało `POST/PUT` karty (walidację rozstrzyga serwer). */
export function buildCardPayload(form: CardFormState, finalize: boolean): TechCardPayload {
  const externals = form.teamExternals.trim();
  return {
    interview_on: form.interviewOn,
    finalize,
    status: form.status === NONE ? null : form.status,
    satisfaction: form.satisfaction === NONE ? null : Number(form.satisfaction),
    client_area_id: form.areaId !== NONE && form.areaId !== NEW_AREA ? Number(form.areaId) : null,
    new_area_name: form.areaId === NEW_AREA ? form.newArea.trim() || null : null,
    skill_ids: form.skills.filter((t) => t.id != null).map((t) => t.id as number),
    skill_names: form.skills.filter((t) => t.id == null).map((t) => t.name),
    vendor_ids: form.vendors.filter((t) => t.id != null).map((t) => t.id as number),
    new_vendor_names: form.vendors.filter((t) => t.id == null).map((t) => t.name),
    hiring: form.hiring ? true : null,
    hiring_source: form.hiring && form.hiringSource !== NONE ? form.hiringSource : null,
    hiring_roles: form.hiring ? splitNames(form.hiringRoles) : [],
    project_end_on: form.projectEndUnknown ? null : monthEnd(form.projectEndMonth),
    project_end_unknown: form.projectEndUnknown,
    team_size: form.teamSize.trim() || null,
    team_externals: externals && /^\d+$/.test(externals) ? Number(externals) : null,
    initiatives: form.initiatives.filter((item) => item.name.trim()),
    memorable_quote: form.quote.trim() || null,
    note: form.note.trim() || null,
  };
}

interface TechCardDialogProps {
  contractId: number;
  clientId: number;
  card: TechCard | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Karta technologiczna: technologie ze słownika umiejętności NEXUSA. */
export function TechCardDialog({
  contractId,
  clientId,
  card,
  open,
  onOpenChange,
}: TechCardDialogProps) {
  const { showToast } = useToast();
  const save = useSaveTechCard(contractId);
  const areas = useClientAreas(clientId, open);
  const today = warsawToday();
  const [form, setForm] = useState<CardFormState>(() => initialCardForm(card, today));
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof CardFormState>(key: K, value: CardFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));
  const skillSearch = useCallback((q: string) => searchSkills(q), []);
  const vendorSearch = useCallback((q: string) => searchVendors(q), []);
  const finalized = card != null && !card.is_draft;

  const submit = (finalize: boolean) => {
    setError(null);
    if (!form.interviewOn || form.interviewOn > today) {
      setError("Podaj datę rozmowy (najpóźniej dzisiejszą).");
      return;
    }
    if ((finalize || finalized) && form.status === NONE) {
      setError("Wybierz status rozmowy.");
      return;
    }
    save.mutate(
      { cardId: card?.id ?? null, payload: buildCardPayload(form, finalize) },
      {
        onSuccess: () => {
          showToast(finalize || finalized ? "Karta zapisana" : "Szkic karty zapisany", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać karty.")),
      },
    );
  };

  const updateInitiative = (index: number, patch: Partial<Initiative>) =>
    set(
      "initiatives",
      form.initiatives.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={card ? "Karta technologiczna" : "Nowa karta technologiczna"}
      description="Co konsultant widzi u klienta. Technologie wybierasz ze słownika umiejętności — nowa nazwa trafi do przejrzenia."
      size="xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          {!finalized ? (
            <Button variant="outline" onClick={() => submit(false)} disabled={save.isPending}>
              Zapisz szkic
            </Button>
          ) : null}
          <Button onClick={() => submit(true)} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : finalized ? "Zapisz kartę" : "Zapisz jako gotową"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="grid content-start gap-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <FormField label="Data rozmowy" htmlFor="care-card-date" required>
              <Input
                id="care-card-date"
                type="date"
                value={form.interviewOn}
                max={today}
                onChange={(event) => set("interviewOn", event.target.value)}
              />
            </FormField>
            <FormField label="Status" htmlFor="care-card-status">
              <Select value={form.status} onValueChange={(v) => set("status", v as CardFormState["status"])}>
                <SelectTrigger id="care-card-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Wybierz…</SelectItem>
                  {(Object.keys(CARD_STATUS_LABELS) as CardStatus[]).map((key) => (
                    <SelectItem key={key} value={key}>
                      {CARD_STATUS_LABELS[key]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField label="Zadowolenie" htmlFor="care-card-score">
              <Select value={form.satisfaction} onValueChange={(v) => set("satisfaction", v)}>
                <SelectTrigger id="care-card-score">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Bez oceny</SelectItem>
                  {[5, 4, 3, 2, 1].map((score) => (
                    <SelectItem key={score} value={String(score)}>
                      {score} / 5
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </div>
          <TokenPicker
            label="Technologie"
            value={form.skills}
            onChange={(next) => set("skills", next)}
            search={skillSearch}
            placeholder="Zacznij pisać, np. Java, Kafka"
            freeTextHint="do przejrzenia"
          />
          <TokenPicker
            label="Dostawcy u klienta"
            value={form.vendors}
            onChange={(next) => set("vendors", next)}
            search={vendorSearch}
            placeholder="Firma zewnętrzna w zespole"
            freeTextHint="nowy"
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Obszar u klienta" htmlFor="care-card-area">
              <Select value={form.areaId} onValueChange={(v) => set("areaId", v)}>
                <SelectTrigger id="care-card-area">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Bez obszaru</SelectItem>
                  {(areas.data ?? []).map((area) => (
                    <SelectItem key={area.id} value={String(area.id)}>
                      {area.name}
                    </SelectItem>
                  ))}
                  <SelectItem value={NEW_AREA}>Nowy obszar…</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            {form.areaId === NEW_AREA ? (
              <FormField label="Nazwa obszaru" htmlFor="care-card-new-area">
                <Input
                  id="care-card-new-area"
                  value={form.newArea}
                  maxLength={120}
                  placeholder="np. Płatności"
                  onChange={(event) => set("newArea", event.target.value)}
                />
              </FormField>
            ) : null}
          </div>
          {areas.isError ? (
            <p className="text-xs text-destructive">Nie udało się wczytać obszarów klienta.</p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Wielkość zespołu" htmlFor="care-card-team">
              <Input
                id="care-card-team"
                value={form.teamSize}
                maxLength={80}
                placeholder="np. 9 osób"
                onChange={(event) => set("teamSize", event.target.value)}
              />
            </FormField>
            <FormField label="W tym z zewnątrz" htmlFor="care-card-externals">
              <Input
                id="care-card-externals"
                inputMode="numeric"
                value={form.teamExternals}
                onChange={(event) => set("teamExternals", event.target.value)}
              />
            </FormField>
          </div>
        </div>
        <div className="grid content-start gap-3">
          <div className="grid gap-2 rounded-md border border-border/60 p-3">
            <label className="flex items-center justify-between gap-2 text-sm font-medium">
              Klient zatrudnia
              <Switch
                checked={form.hiring}
                onCheckedChange={(v) => set("hiring", v)}
                aria-label="Klient zatrudnia"
              />
            </label>
            {form.hiring ? (
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_140px]">
                <FormField label="Kogo szuka" htmlFor="care-card-roles" description="Role po przecinku.">
                  <Input
                    id="care-card-roles"
                    value={form.hiringRoles}
                    placeholder="np. Java, QA"
                    onChange={(event) => set("hiringRoles", event.target.value)}
                  />
                </FormField>
                <FormField label="Skąd wie" htmlFor="care-card-source">
                  <Select
                    value={form.hiringSource}
                    onValueChange={(v) => set("hiringSource", v as CardFormState["hiringSource"])}
                  >
                    <SelectTrigger id="care-card-source">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>—</SelectItem>
                      {(Object.keys(HIRING_SOURCE_LABELS) as HiringSource[]).map((key) => (
                        <SelectItem key={key} value={key}>
                          {HIRING_SOURCE_LABELS[key]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormField>
              </div>
            ) : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Koniec projektu (miesiąc)" htmlFor="care-card-end">
              <Input
                id="care-card-end"
                type="month"
                value={form.projectEndMonth}
                disabled={form.projectEndUnknown}
                onChange={(event) => set("projectEndMonth", event.target.value)}
              />
            </FormField>
            <label className="flex items-end gap-2 pb-2 text-sm">
              <Switch
                checked={form.projectEndUnknown}
                onCheckedChange={(v) => set("projectEndUnknown", v)}
                aria-label="Konsultant nie wie, kiedy koniec projektu"
              />
              Nie wie
            </label>
          </div>
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Inicjatywy u klienta</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  set("initiatives", [
                    ...form.initiatives,
                    { name: "", kind: "inne", priority: "normalny" },
                  ])
                }
              >
                Dodaj
              </Button>
            </div>
            {form.initiatives.map((item, index) => (
              <div key={index} className="grid grid-cols-[minmax(0,1fr)_130px_auto] items-center gap-2">
                <Input
                  aria-label="Nazwa inicjatywy"
                  value={item.name}
                  maxLength={200}
                  placeholder="np. migracja Oracle → PostgreSQL"
                  onChange={(event) => updateInitiative(index, { name: event.target.value })}
                />
                <Select
                  value={item.kind}
                  onValueChange={(v) => updateInitiative(index, { kind: v as InitiativeKind })}
                >
                  <SelectTrigger aria-label="Rodzaj inicjatywy">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(INITIATIVE_KIND_LABELS) as InitiativeKind[]).map((key) => (
                      <SelectItem key={key} value={key}>
                        {INITIATIVE_KIND_LABELS[key]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="quiet"
                  size="icon-sm"
                  aria-label="Usuń inicjatywę"
                  onClick={() =>
                    set(
                      "initiatives",
                      form.initiatives.filter((_, i) => i !== index),
                    )
                  }
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            ))}
          </div>
          <FormField label="Cytat z rozmowy" htmlFor="care-card-quote">
            <Input
              id="care-card-quote"
              value={form.quote}
              maxLength={500}
              onChange={(event) => set("quote", event.target.value)}
            />
          </FormField>
          <FormField label="Notatka" htmlFor="care-card-note">
            <Textarea
              id="care-card-note"
              rows={3}
              maxLength={4000}
              value={form.note}
              onChange={(event) => set("note", event.target.value)}
            />
          </FormField>
        </div>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

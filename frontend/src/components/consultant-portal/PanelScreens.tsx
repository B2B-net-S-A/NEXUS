"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CalendarClock, FileText, Mail, Phone, Upload, Video } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  portalApi,
  portalKeys,
  usePortalQuery,
  type PortalMaterial,
  type PortalMe,
  type PortalProtocol,
  type TrainerForm,
} from "@/lib/api/consultant-portal";
import { cn } from "@/lib/utils";

import { BookingDialog } from "./BookingDialog";
import { DocumentsSection } from "./DocumentsSection";
import { NewCaseDialog } from "./NewCaseDialog";
import { CasesSection, FaqSection, MeetingsSection } from "./PortalSections";
import {
  SETTLEMENT_MODES,
  formatDay,
  nextMeeting,
  offsetLabel,
  rateLabel,
  saveBlob,
  slotLabel,
} from "./portal-model";

export function ScreenTitle({ title, lead }: { title: string; lead?: string }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {lead ? <p className="mt-1 max-w-[65ch] text-sm text-muted-foreground">{lead}</p> : null}
    </div>
  );
}

function Panel({
  title,
  action,
  children,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0 rounded-xl border bg-card p-4">
      {title || action ? (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title ? <h2 className="text-sm font-semibold">{title}</h2> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}

function Loading() {
  return <p className="text-sm text-muted-foreground">Wczytujemy…</p>;
}

function Failure({ error, text }: { error: unknown; text: string }) {
  return (
    <p role="alert" className="text-sm text-destructive">
      {apiErrorMessage(error, text)}
    </p>
  );
}

function ContactLines({ me }: { me: PortalMe }) {
  return (
    <div className="space-y-2 text-sm">
      {me.support_phone ? (
        <p className="flex items-center gap-2 font-semibold">
          <Phone aria-hidden className="size-4 text-primary" /> {me.support_phone}
        </p>
      ) : null}
      {me.support_email ? (
        <p className="flex items-center gap-2 break-all font-semibold">
          <Mail aria-hidden className="size-4 shrink-0 text-primary" /> {me.support_email}
        </p>
      ) : null}
    </div>
  );
}

// ── Start ────────────────────────────────────────────────────────────────────

export function StartScreen({ me }: { me: PortalMe }) {
  const todo = usePortalQuery(portalKeys.todo, portalApi.todo);
  const meetings = usePortalQuery(portalKeys.meetings, portalApi.meetings);
  const next = nextMeeting(meetings.data?.items ?? []);
  const count = todo.data?.items.length ?? 0;
  return (
    <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-4">
        <ScreenTitle
          title={me.first_name ? `Cześć, ${me.first_name}` : "Cześć"}
          lead={todo.isSuccess ? (count ? "Oto, co czeka na Ciebie." : "Nic na Ciebie nie czeka.") : undefined}
        />
        <Panel title="Do zrobienia">
          {todo.isLoading ? <Loading /> : null}
          {todo.isError ? <Failure error={todo.error} text="Nie udało się wczytać listy. Odśwież stronę." /> : null}
          {todo.isSuccess && count === 0 ? (
            <p className="text-sm text-muted-foreground">Gdy pojawi się coś do zrobienia, zobaczysz to tutaj.</p>
          ) : null}
          {todo.isSuccess && count > 0 ? (
            <ul className="divide-y">
              {todo.data.items.map((row) => (
                <li
                  key={row.key}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
                >
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{row.title}</span>
                    <span className="block text-xs text-muted-foreground">{row.detail}</span>
                  </span>
                  <Button size="sm" variant="outline" asChild>
                    <Link href={row.href}>Otwórz</Link>
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>
      </div>
      <div className="min-w-0 space-y-4">
        <Panel title="Twoja współpraca">
          <dl className="grid grid-cols-2 gap-3">
            <Fact label="Klient" value={me.client ?? "Brak danych"} />
            <Fact label="Stawka" value={rateLabel(me.rate) ?? "Brak danych"} />
            <Fact label="Z nami od" value={formatDay(me.since)} />
            {me.until ? <Fact label="Umowa do" value={formatDay(me.until)} /> : null}
          </dl>
        </Panel>
        {next ? (
          <Panel title="Najbliższa rozmowa">
            <p className="text-sm font-medium">{slotLabel(next.start_at)}</p>
            <p className="text-xs text-muted-foreground">
              {[next.topic_label, next.host].filter(Boolean).join(", ")}
            </p>
            <Button size="sm" className="mt-3 w-full" asChild>
              <Link href="/konsultant/rozmowy">
                <Video aria-hidden className="size-3.5" /> Otwórz rozmowy
              </Link>
            </Button>
          </Panel>
        ) : null}
        <Panel title="Potrzebujesz pomocy?">
          <ContactLines me={me} />
        </Panel>
      </div>
    </div>
  );
}

// ── Na start ─────────────────────────────────────────────────────────────────

function MaterialRow({ material }: { material: PortalMaterial }) {
  const [error, setError] = useState<string | null>(null);
  const download = async () => {
    setError(null);
    try {
      saveBlob(await portalApi.downloadMaterial(material.id), material.file_name ?? material.title);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się pobrać pliku."));
    }
  };
  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="min-w-0 font-medium">{material.title}</span>
        {material.kind === "link" && material.url ? (
          <Button size="sm" variant="ghost" asChild>
            <a href={material.url} target="_blank" rel="noreferrer noopener">
              Otwórz
            </a>
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={download}>
            Pobierz
          </Button>
        )}
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function StartMaterialsScreen({ me }: { me: PortalMe }) {
  const start = usePortalQuery(portalKeys.start, portalApi.start);
  return (
    <div className="min-w-0 space-y-4">
      <ScreenTitle
        title="Na start"
        lead={me.client ? `Wszystko, czego potrzebujesz na początek pracy: ${me.client}.` : undefined}
      />
      {start.isLoading ? <Loading /> : null}
      {start.isError ? <Failure error={start.error} text="Nie udało się wczytać tego ekranu. Odśwież stronę." /> : null}
      {start.isSuccess ? (
        <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-2">
          <div className="min-w-0 space-y-4">
            <Panel title="Pierwszy dzień">
              <dl className="space-y-2">
                <Fact
                  label="Kiedy"
                  value={[
                    start.data.start_date ? formatDay(start.data.start_date) : null,
                    start.data.first_day?.time,
                  ]
                    .filter(Boolean)
                    .join(", ") || "Damy znać"}
                />
                {start.data.first_day?.place ? <Fact label="Gdzie" value={start.data.first_day.place} /> : null}
                {start.data.first_day?.contact_name ? (
                  <Fact label="Kto Cię odbierze" value={start.data.first_day.contact_name} />
                ) : null}
                {start.data.first_day?.bring ? <Fact label="Co zabrać" value={start.data.first_day.bring} /> : null}
              </dl>
            </Panel>
            {start.data.documents.length > 0 ? (
              <Panel title="Dokumenty do dostarczenia">
                <ul className="divide-y text-sm">
                  {start.data.documents.map((row) => (
                    <li key={row.name} className="py-2.5 first:pt-0 last:pb-0">
                      <span className="block font-medium">{row.name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {[offsetLabel(row.offset_days), row.note].filter(Boolean).join(". ")}
                      </span>
                    </li>
                  ))}
                </ul>
                {me.support_email ? (
                  <p className="mt-2 text-xs text-muted-foreground">Dokumenty wyślij na {me.support_email}.</p>
                ) : null}
              </Panel>
            ) : null}
          </div>
          <Panel title="Materiały">
            {start.data.materials.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nie mamy dla Ciebie osobnych materiałów.</p>
            ) : (
              <ul className="divide-y">
                {start.data.materials.map((material) => (
                  <MaterialRow key={material.id} material={material} />
                ))}
              </ul>
            )}
          </Panel>
        </div>
      ) : null}
    </div>
  );
}

// ── Rozliczenia ──────────────────────────────────────────────────────────────

export function SettlementScreen({ me }: { me: PortalMe }) {
  const settlement = usePortalQuery(portalKeys.settlement, portalApi.settlement);
  const mode = settlement.data?.mode ? SETTLEMENT_MODES[settlement.data.mode] : null;
  return (
    <div className="min-w-0 space-y-4">
      <ScreenTitle
        title="Jak się rozliczasz"
        lead={me.client ? `Sposób rozliczenia ustala klient. Ten opis dotyczy klienta: ${me.client}.` : undefined}
      />
      {settlement.isLoading ? <Loading /> : null}
      {settlement.isError ? (
        <Failure error={settlement.error} text="Nie udało się wczytać tego ekranu. Odśwież stronę." />
      ) : null}
      {settlement.isSuccess ? (
        <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Panel title={mode ? mode.label : "Rozliczenie"}>
            {mode ? (
              <>
                <p className="max-w-[65ch] text-sm text-muted-foreground">{mode.intro}</p>
                <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm">
                  {mode.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                  <li>Przelew w ciągu {settlement.data.payment_days} dni od nadania numeru KSeF.</li>
                </ol>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Sposób rozliczenia dla Twojego klienta ustalają jeszcze Finanse. Do tego czasu rozliczaj się jak dotąd.
              </p>
            )}
            {settlement.data.instructions ? (
              <p className="mt-3 whitespace-pre-line rounded-lg bg-muted p-3 text-sm">{settlement.data.instructions}</p>
            ) : null}
          </Panel>
          <div className="min-w-0 space-y-4">
            <Panel title="Twoja stawka">
              <p className="text-xl font-semibold tabular-nums">{rateLabel(me.rate) ?? "Brak danych"}</p>
            </Panel>
            <Panel title="Dane na fakturę">
              <dl className="space-y-2">
                <Fact label="Nabywca" value={settlement.data.buyer.name} />
                <Fact label="NIP" value={settlement.data.buyer.nip} />
                <Fact label="Adres" value={settlement.data.buyer.address} />
              </dl>
            </Panel>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── Faktury ──────────────────────────────────────────────────────────────────

export function InvoicesScreen() {
  return (
    <div className="min-w-0 space-y-4">
      <ScreenTitle
        title="Faktury"
        lead="Tu wysyłasz raporty i faktury oraz widzisz, co się z nimi dzieje."
      />
      <DocumentsSection />
    </div>
  );
}

// ── Rozmowy ──────────────────────────────────────────────────────────────────

export function TalksScreen({ me }: { me: PortalMe }) {
  const meetings = usePortalQuery(portalKeys.meetings, portalApi.meetings);
  const [booking, setBooking] = useState(false);
  return (
    <div className="min-w-0 space-y-4">
      <ScreenTitle
        title="Rozmowy z back office'em"
        lead="Wybierz osobę i godzinę. Rozmowa trwa 20 minut i odbywa się w Teams."
      />
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-sm font-medium">
            <CalendarClock aria-hidden className="size-4 text-primary" /> Umów rozmowę
          </p>
          <Button size="sm" onClick={() => setBooking(true)}>
            Wybierz termin
          </Button>
        </div>
      </Panel>
      {meetings.isLoading ? <Loading /> : null}
      <MeetingsSection data={meetings.data?.items} isError={meetings.isError} error={meetings.error} />
      {meetings.isSuccess && meetings.data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nie masz jeszcze żadnej rozmowy.</p>
      ) : null}
      {booking ? <BookingDialog me={me} note={meetings.data?.note ?? null} onClose={() => setBooking(false)} /> : null}
    </div>
  );
}

// ── Sprzęt ───────────────────────────────────────────────────────────────────

function ConfirmDialog({ protocol, onClose }: { protocol: PortalProtocol; onClose: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await portalApi.confirmProtocol(protocol.id, name.trim());
      await Promise.all([
        client.invalidateQueries({ queryKey: portalKeys.equipment }),
        client.invalidateQueries({ queryKey: portalKeys.todo }),
      ]);
      onClose();
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się potwierdzić odbioru. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Potwierdź odbiór sprzętu"
    >
      <div className="space-y-3 text-sm">
        <p>
          Potwierdzasz protokół {protocol.number}: {protocol.items.join(", ")}. Później zatwierdzi go recepcja.
        </p>
        <FormField label="Imię i nazwisko" htmlFor="protocol-signer">
          <Input id="protocol-signer" autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} />
        </FormField>
        {error ? (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Wróć
          </Button>
          <Button disabled={busy || name.trim().length < 3} onClick={submit}>
            Potwierdzam odbiór
          </Button>
        </div>
      </div>
    </AppModal>
  );
}

export function EquipmentScreen({ me }: { me: PortalMe }) {
  const equipment = usePortalQuery(portalKeys.equipment, portalApi.equipment);
  const [confirming, setConfirming] = useState<PortalProtocol | null>(null);
  const [reporting, setReporting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const download = async (protocol: { id: number; number: string }) => {
    setFailure(null);
    try {
      saveBlob(await portalApi.downloadProtocol(protocol.id), `${protocol.number.replaceAll("/", "-")}.pdf`);
    } catch (issue) {
      setFailure(apiErrorMessage(issue, "Nie udało się pobrać protokołu."));
    }
  };
  return (
    <div className="min-w-0 space-y-4">
      <ScreenTitle
        title="Twój sprzęt"
        lead="Sprzęt od B2B.net z protokołami przekazania. Hasła i kody PIN są poza panelem."
      />
      {equipment.isLoading ? <Loading /> : null}
      {equipment.isError ? <Failure error={equipment.error} text="Nie udało się wczytać sprzętu. Odśwież stronę." /> : null}
      {failure ? (
        <p role="alert" className="text-sm text-destructive">
          {failure}
        </p>
      ) : null}
      {equipment.isSuccess ? (
        <>
          <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <Panel title="Masz u siebie">
              {equipment.data.items.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nie masz teraz sprzętu z protokołem.</p>
              ) : (
                <ul className="divide-y text-sm">
                  {equipment.data.items.map((row) => (
                    <li key={row.id} className="flex flex-wrap items-start justify-between gap-2 py-3 first:pt-0 last:pb-0">
                      <span className="min-w-0">
                        <span className="block font-medium">{row.name}</span>
                        <span className="block text-xs text-muted-foreground">
                          {[
                            row.inventory_number ? `Nr ewid. ${row.inventory_number}` : null,
                            row.serial_number ? `S/N ${row.serial_number}` : null,
                            `od ${formatDay(row.since)}`,
                          ]
                            .filter(Boolean)
                            .join(", ")}
                        </span>
                      </span>
                      <Badge variant={row.protocol_status === "oczekuje" ? "warning" : "success"}>{row.protocol_label}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <div className="min-w-0 space-y-4">
              <Panel title="Coś nie działa?">
                <p className="text-sm text-muted-foreground">
                  Awarię, zgubienie albo sprzęt, którego nie masz, zgłoś tutaj.
                </p>
                <Button size="sm" variant="outline" className="mt-3" onClick={() => setReporting(true)}>
                  Zgłoś problem ze sprzętem
                </Button>
              </Panel>
              <Panel title="Zwrot">
                <p className="text-sm text-muted-foreground">
                  Przed końcem współpracy recepcja napisze, co i dokąd oddać. Po zwrocie protokół będzie tutaj.
                </p>
              </Panel>
            </div>
          </div>
          <Panel title="Protokoły">
            {equipment.data.protocols.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nie masz jeszcze protokołów.</p>
            ) : (
              <ul className="divide-y text-sm">
                {equipment.data.protocols.map((row) => (
                  <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0">
                    <span className="min-w-0">
                      <span className="block font-medium">
                        {row.kind === "wydanie" ? "Wydanie" : "Zwrot"} {row.number}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {formatDay(row.date)}, {row.items.join(", ")}. {row.label}.
                      </span>
                    </span>
                    <span className="flex flex-wrap gap-2">
                      {row.can_confirm ? (
                        <Button size="sm" onClick={() => setConfirming(row)}>
                          Potwierdź odbiór
                        </Button>
                      ) : null}
                      <Button size="sm" variant="outline" onClick={() => download(row)}>
                        <FileText aria-hidden className="size-3.5" /> Pobierz PDF
                      </Button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </>
      ) : null}
      {confirming ? <ConfirmDialog protocol={confirming} onClose={() => setConfirming(null)} /> : null}
      {reporting ? (
        <NewCaseDialog
          me={me}
          initialTopic="access"
          initialTitle="Problem ze sprzętem"
          onClose={() => setReporting(false)}
        />
      ) : null}
    </div>
  );
}

// ── Pomoc ────────────────────────────────────────────────────────────────────

export function HelpScreen({ me }: { me: PortalMe }) {
  const [newCase, setNewCase] = useState(false);
  return (
    <div className="min-w-0 space-y-4">
      <ScreenTitle title="Pomoc" lead="Jeden numer i jeden adres do wszystkiego. Sprawę przekażemy właściwej osobie." />
      <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">
        <Panel title="Napisz lub zadzwoń">
          <ContactLines me={me} />
        </Panel>
        <Panel title="Porozmawiaj w Teams">
          <p className="text-xs text-muted-foreground">Wybierasz osobę i godzinę, 20 minut.</p>
          <Button size="sm" className="mt-2" asChild>
            <Link href="/konsultant/rozmowy">Umów rozmowę</Link>
          </Button>
        </Panel>
      </div>
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={() => setNewCase(true)}>
          Nowe zgłoszenie
        </Button>
      </div>
      <CasesSection />
      <FaqSection me={me} />
      {newCase ? <NewCaseDialog me={me} onClose={() => setNewCase(false)} /> : null}
    </div>
  );
}

// ── Zostań trenerem ──────────────────────────────────────────────────────────

const TRAINER_TOPICS = ["AWS", "Azure", "Kubernetes", "Java", "Python", "Testy", "Bezpieczeństwo", "Scrum"];
const TRAINER_FORMS: { value: TrainerForm; label: string }[] = [
  { value: "online_or_onsite", label: "Online lub u klienta" },
  { value: "online", label: "Tylko online" },
  { value: "onsite", label: "Tylko u klienta" },
];

export function TrainerScreen() {
  const client = useQueryClient();
  const saved = usePortalQuery(portalKeys.trainer, portalApi.trainer);
  const [editing, setEditing] = useState(false);
  const [topics, setTopics] = useState<string[]>([]);
  const [other, setOther] = useState("");
  const [experience, setExperience] = useState("");
  const [form, setForm] = useState<TrainerForm>("online_or_onsite");
  const [dayRate, setDayRate] = useState("");
  const [availability, setAvailability] = useState("");
  const [materials, setMaterials] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const application = saved.data?.application ?? null;

  useEffect(() => {
    if (!application) return;
    setTopics(application.topics);
    setExperience(application.experience);
    setForm(application.form);
    setDayRate(application.day_rate);
    setAvailability(application.availability);
    setMaterials(application.materials);
  }, [application]);

  const toggle = (topic: string) =>
    setTopics((list) => (list.includes(topic) ? list.filter((item) => item !== topic) : [...list, topic]));
  const extra = other.trim();
  const allTopics = extra && !topics.includes(extra) ? [...topics, extra] : topics;
  const ready = allTopics.length > 0 && experience.trim().length >= 3;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await portalApi.saveTrainer({
        topics: allTopics,
        experience: experience.trim(),
        form,
        day_rate: dayRate.trim(),
        availability: availability.trim(),
        materials: materials.trim(),
      });
      await Promise.all([
        client.invalidateQueries({ queryKey: portalKeys.trainer }),
        client.invalidateQueries({ queryKey: portalKeys.cases }),
      ]);
      setOther("");
      setEditing(false);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać zgłoszenia. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };

  if (saved.isLoading) return <Loading />;
  if (saved.isError) return <Failure error={saved.error} text="Nie udało się wczytać tego ekranu. Odśwież stronę." />;

  if (application && !editing) {
    return (
      <div className="min-w-0 space-y-4">
        <ScreenTitle title="Dziękujemy za zgłoszenie" lead="Przejrzymy Twoją ofertę i odezwiemy się w tej sprawie." />
        <Panel title="Stan zgłoszenia">
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Fact label="Wysłane" value={formatDay(application.sent_at)} />
            <Fact label="Stan" value={application.waiting.label} />
            <Fact label="Tematy" value={application.topics.join(", ")} />
          </dl>
          <Button size="sm" variant="outline" className="mt-3" onClick={() => setEditing(true)}>
            Popraw zgłoszenie
          </Button>
        </Panel>
      </div>
    );
  }

  return (
    <div className="min-w-0 space-y-4">
      <ScreenTitle
        title="Chcesz zostać trenerem?"
        lead="Opisz, czego możesz uczyć. Weźmiemy Twoją ofertę pod uwagę, gdy klient będzie szukał szkolenia."
      />
      <div className="max-w-3xl">
        <Panel>
          <form className="space-y-4" onSubmit={submit}>
            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium">Tematy szkoleń</legend>
              <div className="flex flex-wrap gap-1.5">
                {[...new Set([...TRAINER_TOPICS, ...topics])].map((topic) => (
                  <button
                    key={topic}
                    type="button"
                    aria-pressed={topics.includes(topic)}
                    onClick={() => toggle(topic)}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-xs",
                      topics.includes(topic) ? "border-primary bg-primary text-primary-foreground" : "bg-card",
                    )}
                  >
                    {topic}
                  </button>
                ))}
              </div>
              <Input
                aria-label="Inny temat"
                placeholder="Inny temat"
                value={other}
                onChange={(event) => setOther(event.target.value)}
              />
            </fieldset>
            <FormField label="Doświadczenie trenerskie" htmlFor="trainer-experience">
              <Textarea
                id="trainer-experience"
                rows={3}
                placeholder="Jakie szkolenia prowadzisz, dla kogo i od kiedy?"
                value={experience}
                onChange={(event) => setExperience(event.target.value)}
              />
            </FormField>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <FormField label="Forma" htmlFor="trainer-form">
                <select
                  id="trainer-form"
                  className="h-9 w-full rounded-md border bg-card px-2 text-sm"
                  value={form}
                  onChange={(event) => setForm(event.target.value as TrainerForm)}
                >
                  {TRAINER_FORMS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label="Stawka za dzień netto" htmlFor="trainer-rate">
                <Input id="trainer-rate" placeholder="np. 4 000 zł" value={dayRate} onChange={(event) => setDayRate(event.target.value)} />
              </FormField>
              <FormField label="Dostępność" htmlFor="trainer-availability">
                <Input
                  id="trainer-availability"
                  placeholder="np. 2 dni w miesiącu"
                  value={availability}
                  onChange={(event) => setAvailability(event.target.value)}
                />
              </FormField>
            </div>
            <FormField label="Materiały lub program" htmlFor="trainer-materials">
              <Input
                id="trainer-materials"
                placeholder="Link albo krótki opis"
                value={materials}
                onChange={(event) => setMaterials(event.target.value)}
              />
            </FormField>
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
            <Button type="submit" disabled={busy || !ready}>
              <Upload aria-hidden className="size-4" /> Wyślij zgłoszenie
            </Button>
          </form>
        </Panel>
      </div>
    </div>
  );
}

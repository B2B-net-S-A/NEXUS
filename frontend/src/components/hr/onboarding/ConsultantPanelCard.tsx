"use client";

// Panel konsultanta w zakładce „Start i sprzęt” kontraktu. Panel nie powstaje sam: po podpisaniu
// umowy osoba z Opieki sprawdza adres, materiały i mail, a dopiero jej klik otwiera dostęp.
// Sekcję widzi tylko operator panelu (`me.consultant_panel_operator` z `/api/hr/config`);
// reszta nie pyta serwera, który odmówiłby 403 w konsoli (Tester 23.11.2026, DL i Finanse). Wariant A (20.11.2026):
// stan jednym wierszem, aktywacja w oknie; tryb panelu to ustawienie całej firmy, więc tu
// widać jego stan, a administrator zmienia go w osobnym oknie „Tryb panelu w firmie”.

import { useEffect, useRef, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  usePanelActivate,
  usePanelAddMaterial,
  usePanelDeactivate,
  usePanelProposal,
  usePanelRetireMaterial,
  usePanelSendWelcome,
  usePanelSwitches,
  useSavePanelSwitches,
  PANEL_STATE_OPTIONS,
  panelOpenForConsultants,
  type PanelProposal,
  type PanelState,
} from "@/lib/api/consultant-panel";
import { useHrConfig } from "@/lib/api/hr";
import { resolveViewState } from "@/lib/view-state";

function shortDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Warsaw",
  });
}

function AdminSwitches() {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const switches = usePanelSwitches(true);
  const save = useSavePanelSwitches();
  const apply = async (
    body: { state?: PanelState; welcome_mail?: boolean },
    title: string,
    description: string,
  ) => {
    const ok = await askConfirm({ title, description, confirmLabel: "Tak", cancelLabel: "Zostaw" });
    if (!ok) return;
    try {
      await save.mutateAsync(body);
    } catch (failure) {
      showToast(apiErrorMessage(failure, "Nie udało się zapisać przełącznika."), "error");
    }
  };
  if (!switches.data) return null;
  const current = switches.data.state;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg bg-muted p-3 text-sm">
      <span className="flex flex-wrap items-center gap-2">
        <span id="panel-state-label">Panel konsultanta</span>
        <SegmentedRadio
          labelledBy="panel-state-label"
          size="sm"
          value={current}
          disabled={save.isPending}
          options={PANEL_STATE_OPTIONS.map(({ value, label }) => ({ value, label }))}
          onChange={(next) => {
            const option = PANEL_STATE_OPTIONS.find((o) => o.value === next);
            if (!option || next === current) return;
            void apply({ state: next }, `Panel konsultanta: ${option.label}?`, option.confirm);
          }}
        />
      </span>
      <label className="flex items-center gap-2">
        <Switch
          checked={switches.data.welcome_mail}
          disabled={save.isPending}
          onCheckedChange={(next) =>
            apply(
              { welcome_mail: next },
              next ? "Włączyć maile powitalne?" : "Wyłączyć maile powitalne?",
              next
                ? "To wysyłka do osób spoza firmy. Mail wychodzi dopiero po kliknięciu przy aktywacji."
                : "Aktywacja będzie działać bez maila.",
            )
          }
        />
        Maile powitalne
      </label>
      {confirmDialog}
    </div>
  );
}

function AddMaterialDialog({
  contractId,
  clientId,
  clientName,
  onClose,
}: {
  contractId: number;
  clientId: number | null;
  clientName: string | null;
  onClose: () => void;
}) {
  const add = usePanelAddMaterial(contractId);
  const [title, setTitle] = useState("");
  const [shared, setShared] = useState(false);
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ready = title.trim().length > 0 && (Boolean(url.trim()) !== Boolean(file));
  const submit = async () => {
    setError(null);
    try {
      await add.mutateAsync({
        title: title.trim(),
        clientId: shared ? null : clientId,
        url: url.trim() || undefined,
        file: file ?? undefined,
      });
      onClose();
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się dodać materiału."));
    }
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Dodaj materiał"
    >
      <div className="space-y-3 text-sm">
        <FormField label="Nazwa" htmlFor="material-title">
          <Input id="material-title" value={title} onChange={(event) => setTitle(event.target.value)} />
        </FormField>
        <FormField label="Link (https)" htmlFor="material-url">
          <Input
            id="material-url"
            placeholder="https://"
            disabled={Boolean(file)}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
        </FormField>
        <FormField label="Albo plik" htmlFor="material-file">
          <Input
            id="material-file"
            type="file"
            accept=".pdf,.docx,.jpg,.jpeg,.png"
            disabled={Boolean(url.trim())}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </FormField>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={shared} onChange={(event) => setShared(event.target.checked)} />
          Dla wszystkich konsultantów, nie tylko: {clientName ?? "ten klient"}
        </label>
        {error ? (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Wróć
          </Button>
          <Button disabled={!ready || add.isPending} onClick={submit}>
            Dodaj materiał
          </Button>
        </div>
      </div>
    </AppModal>
  );
}

/** Adres dopiero co wpisany w formularzu: braku w kontrakcie nie liczymy jako blokady. */
const ADDRESS_ISSUES = new Set(["no_email", "bad_email"]);

export function mailBlocker(data: PanelProposal, { addressTyped }: { addressTyped: boolean }): string | null {
  if (data.mail.sent_at) return "Mail powitalny został już wysłany.";
  if (!data.mail.enabled) return "Maile powitalne są wyłączone, włącza je administrator.";
  if (data.portal_state === "off") return "Panel jest wyłączony dla wszystkich, więc mail prowadziłby donikąd.";
  if (data.portal_state === "internal") return "Panel działa w trybie „Tylko zespół”: konsultanci nie dostają linku ani maili.";
  const blocking = data.mail.issues.find(
    (issue) => issue.blocking && !(addressTyped && ADDRESS_ISSUES.has(issue.code)),
  );
  return blocking ? blocking.message : null;
}

function SendMailDialog({ data, contractId, onClose }: { data: PanelProposal; contractId: number; onClose: () => void }) {
  const { showToast } = useToast();
  const send = usePanelSendWelcome(contractId);
  const [subject, setSubject] = useState(data.mail.subject);
  const [body, setBody] = useState(data.mail.body);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setError(null);
    try {
      await send.mutateAsync({ subject, body });
      showToast("Mail powitalny wysłany.", "success");
      onClose();
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać maila."));
    }
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Mail powitalny"
    >
      <div className="space-y-3 text-sm">
        <FormField label="Temat" htmlFor="panel-send-subject">
          <Input id="panel-send-subject" value={subject} onChange={(event) => setSubject(event.target.value)} />
        </FormField>
        <FormField label="Treść" htmlFor="panel-send-body">
          <Textarea id="panel-send-body" rows={9} value={body} onChange={(event) => setBody(event.target.value)} />
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
          <Button disabled={send.isPending || !subject.trim() || !body.trim()} onClick={submit}>
            Wyślij mail
          </Button>
        </div>
      </div>
    </AppModal>
  );
}

/** „Tylko zespół” — tryb panelu w całej firmie słowem. */
export function panelModeLabel(state: PanelState): string {
  return PANEL_STATE_OPTIONS.find((option) => option.value === state)?.label ?? state;
}

function ActiveState({ data, contractId }: { data: PanelProposal; contractId: number }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const deactivate = usePanelDeactivate(contractId);
  const [sending, setSending] = useState(false);
  const blocker = mailBlocker(data, { addressTyped: false });
  const stop = async () => {
    const ok = await askConfirm({
      title: "Wyłączyć panel tej osoby?",
      description: "Otwarte sesje zamkną się od razu, a nowy link nie zadziała.",
      confirmLabel: "Wyłącz panel",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await deactivate.mutateAsync();
    } catch (failure) {
      showToast(apiErrorMessage(failure, "Nie udało się wyłączyć panelu."), "error");
    }
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-[13px]">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <StatusDot tone="success">aktywny</StatusDot>
        <span className="min-w-0 text-muted-foreground">
          {[
            data.activation.email,
            data.activation.activated_at
              ? `od ${shortDate(data.activation.activated_at)}${
                  data.activation.activated_by ? `, ${data.activation.activated_by}` : ""
                }`
              : null,
            data.mail.sent_at ? `mail wysłany ${shortDate(data.mail.sent_at)}` : "mail nie został wysłany",
            data.activation.last_login_at
              ? `ostatnie logowanie ${shortDate(data.activation.last_login_at)}`
              : "jeszcze bez logowania",
            `tryb firmy: ${panelModeLabel(data.portal_state)}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {data.mail.sent_at ? null : (
          <Button size="sm" variant="outline" disabled={blocker !== null} title={blocker ?? undefined} onClick={() => setSending(true)}>
            Wyślij mail powitalny
          </Button>
        )}
        <Button size="sm" variant="quiet" disabled={deactivate.isPending} onClick={stop}>
          Wyłącz panel…
        </Button>
      </div>
      {sending ? <SendMailDialog data={data} contractId={contractId} onClose={() => setSending(false)} /> : null}
      {confirmDialog}
    </div>
  );
}

function ActivationForm({
  data,
  contractId,
  onDone,
}: {
  data: PanelProposal;
  contractId: number;
  /** Po udanej aktywacji (okno aktywacji się zamyka). */
  onDone?: () => void;
}) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const activate = usePanelActivate(contractId);
  const retire = usePanelRetireMaterial(contractId);
  const [email, setEmail] = useState(data.suggested_email ?? "");
  const [selected, setSelected] = useState<number[]>(
    data.materials.filter((row) => row.selected).map((row) => row.id),
  );
  const [subject, setSubject] = useState(data.mail.subject);
  const [body, setBody] = useState(data.mail.body);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Nowy materiał domyślnie idzie do tej osoby, odznaczone zostają odznaczone, a wycofane
  // wypadają, bo serwer odrzuciłby całą aktywację z materiałem spoza listy.
  const seen = useRef(new Set(data.materials.map((row) => row.id)));
  useEffect(() => {
    const present = new Set(data.materials.map((row) => row.id));
    const fresh = data.materials
      .filter((row) => row.selected && !seen.current.has(row.id))
      .map((row) => row.id);
    fresh.forEach((id) => seen.current.add(id));
    setSelected((list) => [...list.filter((id) => present.has(id)), ...fresh]);
  }, [data.materials]);

  const retireMaterial = async (row: PanelProposal["materials"][number]) => {
    const ok = await askConfirm({
      title: "Wycofać materiał?",
      description: row.shared
        ? `„${row.title}” zniknie z panelu wszystkich konsultantów.`
        : `„${row.title}” zniknie z panelu wszystkich konsultantów tego klienta.`,
      confirmLabel: "Wycofaj",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    retire.mutate(row.id, {
      onError: (failure) => showToast(apiErrorMessage(failure, "Nie udało się wycofać materiału."), "error"),
    });
  };
  const toggle = (id: number) =>
    setSelected((list) => (list.includes(id) ? list.filter((item) => item !== id) : [...list, id]));
  const blocker = mailBlocker(data, { addressTyped: Boolean(email.trim()) });
  const off = !panelOpenForConsultants(data.portal_state);

  const submit = async (sendMail: boolean) => {
    setError(null);
    try {
      const result = await activate.mutateAsync({
        email: email.trim(),
        material_ids: selected,
        send_mail: sendMail,
        subject: sendMail ? subject : undefined,
        body: sendMail ? body : undefined,
      });
      if (result.mail_error) {
        showToast(`Panel aktywny, ale mail nie wyszedł: ${result.mail_error}`, "error");
      } else {
        showToast(sendMail ? "Panel aktywny, mail wysłany." : "Panel aktywny.", "success");
      }
      onDone?.();
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się aktywować panelu."));
    }
  };

  return (
    <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-2">
      <div className="min-w-0 space-y-3">
        <FormField label="Adres do logowania" htmlFor="panel-email">
          <Input
            id="panel-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </FormField>
        <p className="text-xs text-muted-foreground">
          Sprawdź adres z kartoteki. Sam link z maila daje dostęp do stawki i faktur.
        </p>
        <div>
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium">Materiały dla tej osoby</p>
            <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
              Dodaj plik lub link
            </Button>
          </div>
          {data.materials.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nie ma jeszcze materiałów wspólnych ani dla tego klienta.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {data.materials.map((row) => (
                <li key={row.id} className="flex items-center justify-between gap-2">
                  <label className="flex min-w-0 items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selected.includes(row.id)}
                      onChange={() => toggle(row.id)}
                    />
                    <span className="min-w-0">
                      {row.title}{" "}
                      <span className="text-xs text-muted-foreground">
                        ({row.shared ? "wszyscy" : (data.client ?? "klient")})
                      </span>
                    </span>
                  </label>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={retire.isPending}
                    onClick={() => retireMaterial(row)}
                  >
                    Wycofaj
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="min-w-0 space-y-3">
        <FormField label="Temat maila powitalnego" htmlFor="panel-subject">
          <Input id="panel-subject" value={subject} onChange={(event) => setSubject(event.target.value)} />
        </FormField>
        <FormField label="Treść" htmlFor="panel-body">
          <Textarea id="panel-body" rows={9} value={body} onChange={(event) => setBody(event.target.value)} />
        </FormField>
        {data.mail.issues.length > 0 ? (
          <ul className="space-y-1 text-xs text-muted-foreground">
            {data.mail.issues.map((issue) => (
              <li key={issue.code}>{issue.message}</li>
            ))}
          </ul>
        ) : null}
        {blocker ? <p className="text-xs text-muted-foreground">{blocker}</p> : null}
        {off ? (
          <p className="text-xs text-muted-foreground">
            {data.portal_state === "internal"
              ? "Panel działa w trybie „Tylko zespół”. Aktywacja zadziała, gdy administrator wpuści konsultantów."
              : "Panel jest wyłączony dla wszystkich. Aktywacja zadziała, gdy administrator go włączy."}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button disabled={activate.isPending || !email.trim() || blocker !== null} onClick={() => submit(true)}>
            Aktywuj panel i wyślij mail
          </Button>
          <Button variant="outline" disabled={activate.isPending || !email.trim()} onClick={() => submit(false)}>
            Aktywuj bez maila
          </Button>
        </div>
      </div>
      {adding ? (
        <AddMaterialDialog
          contractId={contractId}
          clientId={data.client_id}
          clientName={data.client}
          onClose={() => setAdding(false)}
        />
      ) : null}
      {confirmDialog}
    </div>
  );
}

export function ConsultantPanelCard({ contractId }: { contractId: number }) {
  const me = useHrConfig().data?.me;
  const operator = me?.consultant_panel_operator === true;
  const proposal = usePanelProposal(contractId, operator);
  const isAdmin = me?.is_admin === true;
  const [activating, setActivating] = useState(false);
  const [modeOpen, setModeOpen] = useState(false);
  const state = resolveViewState({
    isLoading: proposal.isLoading,
    error: proposal.error,
    isSuccess: proposal.isSuccess,
  });
  if (!operator || state === "forbidden" || state === "loading") return null;
  const data = state === "ready" ? proposal.data : undefined;
  const addressChanged = Boolean(data?.activation.active && data.activation.address_changed);
  return (
    <section aria-label="Panel konsultanta" className="space-y-1.5 px-4 py-3">
      <div className="flex min-h-8 flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-baseline gap-2 text-[13.5px] font-semibold text-foreground">
          Panel konsultanta{" "}
          <span className="text-[12px] font-normal text-muted-foreground">powstaje dopiero po kliknięciu, konsultant tego nie widzi</span>
        </h3>
        {isAdmin ? (
          <Button size="sm" variant="ghost" onClick={() => setModeOpen(true)}>
            Tryb panelu w firmie…
          </Button>
        ) : null}
      </div>
      {!data ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(proposal.error, "Nie udało się wczytać panelu konsultanta. Odśwież stronę.")}
        </p>
      ) : data.activation.active && !data.activation.address_changed ? (
        <ActiveState data={data} contractId={contractId} />
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 text-[13px]">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <StatusDot tone={addressChanged ? "warning" : "neutral"}>
              {addressChanged ? "zamknięty — zmienił się adres" : "nieaktywny"}
            </StatusDot>
            <span className="text-muted-foreground">
              tryb firmy: <span className="text-foreground">{panelModeLabel(data.portal_state)}</span>
              {isAdmin ? "" : " (zmienia administrator)"}
            </span>
          </div>
          {data.can_activate ? (
            <Button size="sm" variant="outline" onClick={() => setActivating(true)}>
              {addressChanged ? "Potwierdź adres…" : "Aktywuj panel…"}
            </Button>
          ) : (
            <span className="text-[12px] text-muted-foreground">Panel można aktywować przy działającym kontrakcie.</span>
          )}
        </div>
      )}
      {activating && data ? (
        <AppModal
          open
          onOpenChange={(open) => {
            if (!open) setActivating(false);
          }}
          title="Aktywacja panelu konsultanta"
          description="Sprawdź adres, materiały i mail powitalny — panel otwiera się dopiero po kliknięciu."
          size="xl"
        >
          {addressChanged ? (
            <p role="status" className="mb-3 text-sm text-warning-muted-foreground">
              Adres w kontrakcie zmienił się po aktywacji, więc panel jest zamknięty. Potwierdź adres, żeby go otworzyć.
            </p>
          ) : null}
          <ActivationForm data={data} contractId={contractId} onDone={() => setActivating(false)} />
        </AppModal>
      ) : null}
      {modeOpen ? (
        <AppModal
          open
          onOpenChange={setModeOpen}
          title="Tryb panelu w firmie"
          description="Ustawienie dla wszystkich kontraktów — tego samego przełącznika używa „Start rozliczeń” w Finansach."
        >
          <AdminSwitches />
        </AppModal>
      ) : null}
    </section>
  );
}

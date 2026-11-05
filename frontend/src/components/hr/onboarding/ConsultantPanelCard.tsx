"use client";

// Panel konsultanta w zakładce „Wejście” kontraktu. Panel nie powstaje sam: po podpisaniu
// umowy osoba z Opieki sprawdza adres, materiały i mail, a dopiero jej klik otwiera dostęp.
// Bez uprawnień serwer odpowiada 403 i karty po prostu nie ma.

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
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
  usePanelSwitches,
  useSavePanelSwitches,
  type PanelProposal,
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
    body: { state?: "off" | "pilot"; welcome_mail?: boolean },
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
  const on = switches.data.state !== "off";
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg bg-muted p-3 text-sm">
      <label className="flex items-center gap-2">
        <Switch
          checked={on}
          disabled={save.isPending}
          onCheckedChange={(next) =>
            apply(
              { state: next ? "pilot" : "off" },
              next ? "Włączyć panel konsultanta?" : "Wyłączyć panel dla wszystkich?",
              next
                ? "Wejdą tylko osoby z ręczną aktywacją."
                : "Wszystkie sesje konsultantów zostaną zamknięte, a maile do nich przestaną wychodzić.",
            )
          }
        />
        Panel włączony
      </label>
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

function ActiveState({ data, contractId }: { data: PanelProposal; contractId: number }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const deactivate = usePanelDeactivate(contractId);
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
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm">
      <div className="min-w-0">
        <p className="flex items-center gap-2 font-medium">
          <Badge variant="success">Panel aktywny</Badge> {data.activation.email}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {[
            data.activation.activated_at
              ? `Aktywowano ${shortDate(data.activation.activated_at)}${
                  data.activation.activated_by ? `, ${data.activation.activated_by}` : ""
                }`
              : null,
            data.mail.sent_at ? `Mail wysłany ${shortDate(data.mail.sent_at)}` : "Mail nie został wysłany",
            data.activation.last_login_at
              ? `Ostatnie logowanie ${shortDate(data.activation.last_login_at)}`
              : "Jeszcze bez logowania",
          ]
            .filter(Boolean)
            .join(". ")}
          .
        </p>
      </div>
      <Button size="sm" variant="outline" disabled={deactivate.isPending} onClick={stop}>
        Wyłącz panel
      </Button>
      {confirmDialog}
    </div>
  );
}

function ActivationForm({ data, contractId }: { data: PanelProposal; contractId: number }) {
  const { showToast } = useToast();
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

  useEffect(() => {
    // Nowy materiał domyślnie idzie do tej osoby, a odznaczone zostają odznaczone.
    setSelected((list) => {
      const known = new Set(list);
      const fresh = data.materials.filter((row) => row.selected && !known.has(row.id)).map((row) => row.id);
      return fresh.length ? [...list, ...fresh] : list;
    });
  }, [data.materials]);

  const toggle = (id: number) =>
    setSelected((list) => (list.includes(id) ? list.filter((item) => item !== id) : [...list, id]));
  const blocking = data.mail.issues.find((issue) => issue.blocking);
  const mailReady = data.mail.enabled && !blocking && !data.mail.sent_at;
  const off = data.portal_state === "off";

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
                    onClick={() =>
                      retire.mutate(row.id, {
                        onError: (failure) =>
                          showToast(apiErrorMessage(failure, "Nie udało się wycofać materiału."), "error"),
                      })
                    }
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
        {!data.mail.enabled ? (
          <p className="text-xs text-muted-foreground">Maile powitalne są wyłączone, włącza je administrator.</p>
        ) : null}
        {off ? (
          <p className="text-xs text-muted-foreground">
            Panel jest wyłączony dla wszystkich. Aktywacja zadziała, gdy administrator go włączy.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button disabled={activate.isPending || !email.trim() || !mailReady} onClick={() => submit(true)}>
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
    </div>
  );
}

export function ConsultantPanelCard({ contractId }: { contractId: number }) {
  const proposal = usePanelProposal(contractId);
  const isAdmin = useHrConfig().data?.me.is_admin === true;
  const state = resolveViewState({
    isLoading: proposal.isLoading,
    error: proposal.error,
    isSuccess: proposal.isSuccess,
  });
  if (state === "forbidden" || state === "loading") return null;
  return (
    <section className="space-y-3 rounded-xl border bg-card p-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Panel konsultanta</h3>
        <p className="text-xs text-muted-foreground">
          Panel powstaje dopiero po kliknięciu. Tego konsultant nie widzi.
        </p>
      </div>
      {isAdmin ? <AdminSwitches /> : null}
      {state !== "ready" || !proposal.data ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(proposal.error, "Nie udało się wczytać panelu konsultanta. Odśwież stronę.")}
        </p>
      ) : proposal.data.activation.active ? (
        <ActiveState data={proposal.data} contractId={contractId} />
      ) : proposal.data.can_activate ? (
        <ActivationForm data={proposal.data} contractId={contractId} />
      ) : (
        <p className="text-sm text-muted-foreground">Panel można aktywować przy działającym kontrakcie.</p>
      )}
    </section>
  );
}

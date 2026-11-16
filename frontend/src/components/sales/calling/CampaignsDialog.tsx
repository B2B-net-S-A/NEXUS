"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useCallCampaigns, useSaveCampaign, type CallCampaign } from "@/lib/api/sales-calling";

import { plural } from "../my-day";

import { BotListPanel } from "./BotListPanel";

type Editing = CallCampaign | "new" | null;

function campaignLine(campaign: CallCampaign): string {
  const fresh = campaign.counts.new ?? 0;
  const meetings = campaign.counts.meeting_booked ?? 0;
  return [
    campaign.service,
    plural(campaign.total, "rekord", "rekordy", "rekordów"),
    `${fresh} bez rozmowy`,
    plural(meetings, "umówione spotkanie", "umówione spotkania", "umówionych spotkań"),
  ]
    .filter(Boolean)
    .join(" · ");
}

function CampaignForm({ campaign, onDone }: { campaign: CallCampaign | null; onDone: () => void }) {
  const save = useSaveCampaign();
  const { showError, showSuccess } = useToast();
  const [name, setName] = useState(campaign?.name ?? "");
  const [service, setService] = useState(campaign?.service ?? "");
  const [script, setScript] = useState(campaign?.script ?? "");

  const submit = () => {
    save.mutate(
      { id: campaign?.id, name: name.trim(), service: service.trim() || null, script: script.trim() || null },
      {
        onSuccess: () => {
          showSuccess(campaign ? "Zapisano kampanię." : "Dodano kampanię. Teraz zaimportuj do niej listę.");
          onDone();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać kampanii.")),
      },
    );
  };

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="call-campaign-name">Nazwa kampanii</Label>
          <Input
            id="call-campaign-name"
            value={name}
            maxLength={160}
            placeholder="np. Automatyzacje · dyrektorzy operacyjni"
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="call-campaign-service">Usługa</Label>
          <Input
            id="call-campaign-service"
            value={service}
            maxLength={120}
            placeholder="co sprzedajemy w tej kampanii"
            onChange={(event) => setService(event.target.value)}
          />
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor="call-campaign-script">Skrypt rozmowy</Label>
        <Textarea
          id="call-campaign-script"
          rows={8}
          value={script}
          maxLength={20000}
          placeholder={"Otwarcie: …\nPytania: …\nCel rozmowy: …"}
          onChange={(event) => setScript(event.target.value)}
        />
        <p className="text-xs text-muted-foreground">Skrypt widzi dzwoniący na karcie każdego rekordu tej kampanii.</p>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onDone} disabled={save.isPending}>
          Wróć
        </Button>
        <Button onClick={submit} disabled={!name.trim()} loading={save.isPending}>
          {campaign ? "Zapisz" : "Dodaj kampanię"}
        </Button>
      </div>
    </div>
  );
}

interface CampaignsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Otwórz od razu formularz nowej kampanii (z okna importu). */
  startNew?: boolean;
}

/** Kampanie dzwonienia: usługa, lista i skrypt rozmowy. Listę dodaje import. */
export function CampaignsDialog({ open, onOpenChange, startNew = false }: CampaignsDialogProps) {
  const campaigns = useCallCampaigns(open);
  const [editing, setEditing] = useState<Editing>(startNew ? "new" : null);
  const [bot, setBot] = useState<CallCampaign | null>(null);

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={
        bot ? `Bot Listy · ${bot.name}` : editing === null ? "Kampanie" : editing === "new" ? "Nowa kampania" : "Edytuj kampanię"
      }
      description={
        bot
          ? "Opisz, do kogo dzwonimy. Bot buduje listę z bazy i dosypuje ją co poniedziałek."
          : editing === null
            ? "Kampania to usługa, lista firm do obdzwonienia i skrypt rozmowy."
            : undefined
      }
      size="lg"
    >
      {bot ? (
        <BotListPanel campaign={bot} onBack={() => setBot(null)} />
      ) : editing !== null ? (
        <CampaignForm
          key={editing === "new" ? "new" : editing.id}
          campaign={editing === "new" ? null : editing}
          onDone={() => (startNew ? onOpenChange(false) : setEditing(null))}
        />
      ) : campaigns.isError ? (
        <div role="alert" className="flex items-center justify-between gap-3 text-sm text-destructive">
          <span>{apiErrorMessage(campaigns.error, "Nie udało się wczytać kampanii.")}</span>
          <Button size="sm" variant="outline" onClick={() => void campaigns.refetch()}>
            Spróbuj ponownie
          </Button>
        </div>
      ) : !campaigns.isSuccess ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : (
        <div className="space-y-3">
          {campaigns.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nie ma jeszcze żadnej kampanii. Dodaj pierwszą, a potem zaimportuj do niej listę.
            </p>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {campaigns.data.map((campaign) => (
                <li key={campaign.id} className="flex items-center gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1 leading-tight">
                    <p className="truncate text-sm font-medium text-foreground">{campaign.name}</p>
                    <p className="truncate text-xs text-muted-foreground">{campaignLine(campaign)}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 shrink-0"
                    data-tour="sales.calling.bot-lists"
                    onClick={() => setBot(campaign)}
                  >
                    Bot Listy
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 shrink-0" onClick={() => setEditing(campaign)}>
                    Edytuj
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex justify-end">
            <Button onClick={() => setEditing("new")}>Nowa kampania</Button>
          </div>
        </div>
      )}
    </AppModal>
  );
}

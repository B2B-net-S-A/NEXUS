"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ownHiringApi,
  ownHiringKeys,
  type OwnHiringProcess,
  type OwnHiringSettings,
} from "@/lib/api/ownHiring";

const DAYS = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek"];
const NO_ASSISTANT = "none";

function windowsToText(spans: string[][] | undefined): string {
  return (spans ?? []).map(([from, to]) => `${from}-${to}`).join(", ");
}

/** „09:00-11:00, 13:00-14:30” → pary; `null` przy błędnym zapisie. */
export function parseWindows(text: string): string[][] | null {
  const out: string[][] = [];
  for (const part of text.split(",").map((item) => item.trim()).filter(Boolean)) {
    const match = /^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$/.exec(part);
    if (!match) return null;
    out.push([match[1].padStart(5, "0"), match[2].padStart(5, "0")]);
  }
  return out;
}

const NUMBERS: { key: keyof OwnHiringSettings; label: string }[] = [
  { key: "slot_minutes", label: "Rozmowa Teams (min)" },
  { key: "office_minutes", label: "Rozmowa w biurze (min)" },
  { key: "buffer_minutes", label: "Przerwa (min)" },
  { key: "lead_hours", label: "Najwcześniej za (godz.)" },
  { key: "horizon_days", label: "Do przodu (dni)" },
  { key: "response_business_days", label: "Czas na odpowiedź (dni rob.)" },
];

export function SettingsView({ process }: { process: OwnHiringProcess }) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [title, setTitle] = useState(process.title);
  const [ads, setAds] = useState(process.ad_titles.join("\n"));
  const [assistant, setAssistant] = useState(
    process.assistant_user_id === null ? NO_ASSISTANT : String(process.assistant_user_id),
  );
  const [settings, setSettings] = useState<OwnHiringSettings>(process.settings);
  const [windows, setWindows] = useState(() =>
    DAYS.map((_, day) => windowsToText(process.settings.windows[String(day)])),
  );
  const options = useQuery({ queryKey: ["own-hiring", "assistants"], queryFn: ownHiringApi.assistantOptions });
  const save = useMutation({
    mutationFn: () => {
      const parsed = windows.map(parseWindows);
      if (parsed.some((item) => item === null)) {
        throw new Error("Godziny wpisz jako 09:00-11:00, kolejne okna po przecinku.");
      }
      const nextWindows = Object.fromEntries(
        parsed.flatMap((spans, day) => (spans && spans.length ? [[String(day), spans]] : [])),
      );
      return ownHiringApi.saveProcess({
        title: title.trim(),
        ad_titles: ads.split("\n").map((line) => line.trim()).filter(Boolean),
        assistant_user_id: assistant === NO_ASSISTANT ? null : Number(assistant),
        settings: { ...settings, windows: nextWindows },
      });
    },
    onSuccess: () => {
      showSuccess("Zapisano ustawienia");
      void queryClient.invalidateQueries({ queryKey: ownHiringKeys.all });
    },
    onError: (error) =>
      showError(error instanceof Error && !("response" in error) ? error.message : apiErrorMessage(error, "Nie udało się zapisać.")),
  });
  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 overflow-auto p-5 lg:grid-cols-2">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Kiedy można się umówić</h2>
        <p className="text-xs text-muted-foreground">Kandydat zobaczy tylko godziny z tych okien, w których Twój kalendarz jest wolny.</p>
        {DAYS.map((day, index) => (
          <div key={day} className="flex items-center gap-3">
            <label htmlFor={`oh-day-${index}`} className="w-28 text-sm">{day}</label>
            <Input
              id={`oh-day-${index}`}
              placeholder="bez rozmów"
              value={windows[index]}
              onChange={(e) => setWindows((prev) => prev.map((item, i) => (i === index ? e.target.value : item)))}
            />
          </div>
        ))}
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
          {NUMBERS.map(({ key, label }) => (
            <div key={key}>
              <label htmlFor={`oh-${key}`} className="text-xs font-medium text-muted-foreground">{label}</label>
              <Input
                id={`oh-${key}`}
                type="number"
                className="mt-1"
                value={String(settings[key])}
                onChange={(e) => setSettings((prev) => ({ ...prev, [key]: Number(e.target.value) }))}
              />
            </div>
          ))}
        </div>
      </section>
      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Proces</h2>
        <div>
          <label htmlFor="oh-set-title" className="text-xs font-medium text-muted-foreground">Stanowisko (widać je w mailu)</label>
          <Input id="oh-set-title" className="mt-1" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <label htmlFor="oh-set-ads" className="text-xs font-medium text-muted-foreground">Tytuły ogłoszeń, każdy w osobnej linii</label>
          <Textarea id="oh-set-ads" className="mt-1" rows={4} value={ads} onChange={(e) => setAds(e.target.value)} />
        </div>
        <div>
          <p className="text-xs font-medium text-muted-foreground">Asystentka</p>
          <Select value={assistant} onValueChange={setAssistant}>
            <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_ASSISTANT}>Bez asystentki</SelectItem>
              {(options.data ?? []).map((user) => (
                <SelectItem key={user.id} value={String(user.id)}>{user.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {options.isError && <p className="mt-1 text-xs text-destructive">Nie udało się pobrać listy osób.</p>}
        </div>
        <div>
          <label htmlFor="oh-set-address" className="text-xs font-medium text-muted-foreground">Adres biura (do zaproszenia)</label>
          <Input
            id="oh-set-address"
            className="mt-1"
            value={settings.office_address}
            onChange={(e) => setSettings((prev) => ({ ...prev, office_address: e.target.value }))}
          />
        </div>
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>Zapisz</Button>
      </section>
    </div>
  );
}

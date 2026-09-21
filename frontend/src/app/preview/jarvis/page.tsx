"use client";

/**
 * Harness wizualny Jarvisa — PUBLICZNY (`PUBLIC_PATHS`), więc ZERO zapytań:
 * wszystkie komponenty są prezentacyjne i dostają fikcyjne dane z propsów
 * (repo jest publiczne — żadnych prawdziwych nazwisk). Nie montuje
 * `JarvisRoot` — ten woła API.
 *
 * Pokazuje: galerię postaci we wszystkich nastrojach, maskotkę z dymkiem,
 * panel z rozmową (kroki, karta akcji do zatwierdzenia, karta po wykonaniu,
 * link do ekranu, błąd), pusty panel z podpowiedziami, historię rozmów oraz
 * formularz wyglądu z zablokowanymi postaciami.
 */

import { useState } from "react";
import { JARVIS_CHARACTERS, JarvisCharacter } from "@/components/jarvis/characters/JarvisCharacter";
import { JarvisActionCard } from "@/components/jarvis/JarvisActionCard";
import { JarvisAppearanceDialog } from "@/components/jarvis/JarvisAppearanceDialog";
import { JarvisAppearanceForm } from "@/components/jarvis/JarvisAppearanceForm";
import { JarvisMascot } from "@/components/jarvis/JarvisMascot";
import { JarvisMessageList } from "@/components/jarvis/JarvisMessageList";
import { JarvisPanel } from "@/components/jarvis/JarvisPanel";
import type { JarvisAccent, JarvisItem, JarvisMood, JarvisPrefsResponse } from "@/lib/jarvis/types";

const noop = () => undefined;

const MOODS: JarvisMood[] = ["idle", "listening", "thinking", "working", "success", "error"];

const CONVERSATION: JarvisItem[] = [
  { kind: "message", role: "user", markdown: "Kto stoi najdłużej na tablicy rekrutacji Java Developer?" },
  {
    kind: "steps",
    steps: [
      { tool: "list_jobs", label: "Przeglądam rekrutacje…", status: "done" },
      { tool: "get_job_board", label: "Czytam tablicę rekrutacji…", status: "done" },
    ],
  },
  {
    kind: "message",
    role: "assistant",
    markdown:
      "Najdłużej czekają:\n\n- **[Jan Przykładowy](/candidates/101)** — *Zweryfikowany*, 12 dni\n- **[Ewa Testowa](/candidates/102)** — *CV wysłane*, 9 dni\n\nChcesz, żebym przesunął Jana na „Rozmowa z klientem”?",
  },
  { kind: "message", role: "user", markdown: "Tak, i dodaj notatkę, że klient czeka na termin." },
  {
    kind: "action",
    action: {
      id: "demo-1",
      tool: "move_candidate_stage",
      status: "proposed",
      preview: {
        text: "Przesunę **Jan Przykładowy** w **Java Developer / Firma Demo** na etap **Rozmowa z klientem** (teraz: Zweryfikowany)",
      },
    },
  },
  {
    kind: "action",
    action: {
      id: "demo-2",
      tool: "create_note",
      status: "executed",
      preview: { text: "Dodam notatkę do **Jan Przykładowy**: „Klient czeka na propozycję terminu.”" },
    },
  },
  { kind: "message", role: "user", markdown: "🌐 Jakie są dziś stawki senior Go w Warszawie?" },
  {
    kind: "steps",
    steps: [{ tool: "web_search", label: "Szukam w internecie: „stawki senior Go Warszawa 2026”…", status: "done" }],
  },
  {
    kind: "message",
    role: "assistant",
    markdown: "Według świeżych ogłoszeń widełki B2B to zwykle **180–230 zł/h**; górę zakresu płacą fintechy.",
  },
  {
    kind: "sources",
    items: [
      { url: "https://example.org/raport-placowy-it", title: "Raport płacowy IT 2026 (przykład)" },
      { url: "https://example.com/oferty/go", title: "Oferty Go — Warszawa (przykład)" },
    ],
  },
  { kind: "message", role: "user", markdown: "Zakończ współpracę na kontrakcie Ewy." },
  {
    kind: "link",
    href: "/contracts/7",
    label: "Kontrakt",
    reason: "Tego nie zrobię za Ciebie — w kontrakcie kliknij „Zakończ współpracę” i wpisz datę oraz powód.",
  },
  { kind: "error", message: "Nie działam teraz — spróbuj za chwilę. Wszystko inne w NEXUSIE działa normalnie." },
];

const PREFS: JarvisPrefsResponse = {
  character: "owl",
  name: "Sowa",
  accent: "green",
  enabled: true,
  minimized: false,
  sound: false,
  daily_brief: true,
  unlocked_characters: ["robot", "owl", "cat", "ghost", "rocket", "star", "dragon", "astronaut"],
  locked_characters: {
    robot_gold: "Wygraj dowolny ranking Ligi Mistrzów (1. miejsce).",
    trophy: "Stań na podium Ligi Mistrzów (miejsca 1–3).",
  },
};

export default function JarvisPreviewPage() {
  const [accent, setAccent] = useState<JarvisAccent>("primary");
  const [dialogOpen, setDialogOpen] = useState(false);
  return (
    <main className="min-h-screen bg-background p-6 text-foreground">
      <h1 className="text-xl font-semibold">Jarvis — podgląd komponentów</h1>
      <p className="mt-1 text-sm text-muted-foreground">Dane fikcyjne. Strona nie wysyła żadnych zapytań.</p>

      <section className="mt-6">
        <div className="mb-3 flex items-center gap-3">
          <h2 className="text-sm font-semibold">Postaci × nastroje</h2>
          <select
            value={accent}
            onChange={(e) => setAccent(e.target.value as JarvisAccent)}
            className="rounded-md border border-border bg-card px-2 py-1 text-xs"
            aria-label="Akcent"
          >
            {["primary", "violet", "blue", "green", "orange", "rose", "graphite"].map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div className="overflow-x-auto rounded-xl border border-border bg-card p-4">
          <table className="text-center text-xs">
            <thead>
              <tr>
                <th className="px-2 text-left">postać</th>
                {MOODS.map((m) => (
                  <th key={m} className="px-2 font-medium text-muted-foreground">
                    {m}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {JARVIS_CHARACTERS.map((c) => (
                <tr key={c.id}>
                  <td className="px-2 text-left font-medium">{c.label}</td>
                  {MOODS.map((m) => (
                    <td key={m} className="px-2 py-1">
                      <JarvisCharacter id={c.id} accent={accent} mood={m} size={64} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold">Panel i maskotka</h2>
        <div className="flex flex-wrap items-end gap-6">
          <JarvisPanel
            inline
            name="Jarvis"
            character="robot"
            accent={accent}
            mood="listening"
            view="chat"
            items={CONVERSATION.slice(0, 6)}
            thinking={false}
            streaming={false}
            draft=""
            suggestions={[]}
            busyActionId={null}
            onDraftChange={noop}
            onSend={noop}
            onNewChat={noop}
            onShowHistory={noop}
            onBackToChat={noop}
            onSelectConversation={noop}
            onDeleteConversation={noop}
            onOpenAppearance={noop}
            onClose={noop}
            onConfirm={noop}
            onReject={noop}
          />
          <JarvisPanel
            inline
            name="Sowa"
            character="owl"
            accent="green"
            mood="idle"
            view="chat"
            items={[]}
            thinking={false}
            streaming={false}
            draft=""
            webMode
            webRemaining={17}
            onToggleWeb={noop}
            suggestions={["Co mam dziś do zrobienia?", "Jakie mam dziś spotkania?", "Jak dodać zamówienie z PDF-a?"]}
            softLimitNote={null}
            onDraftChange={noop}
            onSend={noop}
            onNewChat={noop}
            onShowHistory={noop}
            onBackToChat={noop}
            onSelectConversation={noop}
            onDeleteConversation={noop}
            onOpenAppearance={noop}
            onClose={noop}
            onConfirm={noop}
            onReject={noop}
          />
          <JarvisPanel
            inline
            name="Jarvis"
            character="robot"
            accent={accent}
            mood="idle"
            view="history"
            items={[]}
            thinking={false}
            streaming={false}
            draft=""
            suggestions={[]}
            conversations={[
              { id: "c1", title: "Kto stoi najdłużej na tablicy rekrutacji Java…", updated_at: "2026-09-21T09:12:00Z" },
              { id: "c2", title: "Jak dodać zamówienie z PDF-a?", updated_at: "2026-09-20T15:40:00Z" },
            ]}
            activeConversationId="c1"
            onDraftChange={noop}
            onSend={noop}
            onNewChat={noop}
            onShowHistory={noop}
            onBackToChat={noop}
            onSelectConversation={noop}
            onDeleteConversation={noop}
            onOpenAppearance={noop}
            onClose={noop}
            onConfirm={noop}
            onReject={noop}
          />
          <div className="flex flex-col items-end gap-6">
            <JarvisMascot
              inline
              name="Jarvis"
              character="robot"
              accent={accent}
              mood="idle"
              minimized={false}
              open={false}
              bubble="Na dziś: 3 nowe powiadomienia, 2 wydarzenia w kalendarzu. Kliknij, a podpowiem, od czego zacząć."
              attention
              onToggle={noop}
              onDismissBubble={noop}
            />
            <JarvisMascot inline name="Jarvis" character="cat" accent="rose" mood="idle" minimized open={false} onToggle={noop} />
          </div>
        </div>
      </section>

      <div className="mt-8 grid gap-8 lg:grid-cols-2">
        <section>
          <h2 className="mb-3 text-sm font-semibold">Rozmowa (kroki, akcje, link, błąd)</h2>
          <div className="max-w-[420px] rounded-2xl border border-border bg-card p-3">
            <JarvisMessageList items={CONVERSATION} thinking assistantName="Jarvis" />
          </div>
        </section>
        <section className="space-y-6">
          <div>
            <h2 className="mb-3 text-sm font-semibold">Karty akcji — stany</h2>
            <div className="max-w-[420px] space-y-2">
              {(["rejected", "failed", "expired"] as const).map((status) => (
                <JarvisActionCard
                  key={status}
                  action={{
                    id: status,
                    tool: "create_note",
                    status,
                    preview: { text: "Dodam notatkę do **Jan Przykładowy**" },
                    result: status === "failed" ? { error: "Brak uprawnień użytkownika do tych danych" } : null,
                  }}
                />
              ))}
              <JarvisActionCard
                action={{
                  id: "warn",
                  tool: "move_candidate_stage",
                  status: "proposed",
                  preview: {
                    text: "Przesunę **Ewa Testowa** na etap **CV wysłane** — mimo ostrzeżenia",
                    warning: "Kandydatka ma aktywne NDA z tym klientem.",
                  },
                }}
              />
            </div>
          </div>
          <div>
            <h2 className="mb-3 text-sm font-semibold">Wygląd asystenta — okno (jak w aplikacji)</h2>
            <button
              type="button"
              data-testid="open-appearance-dialog"
              onClick={() => setDialogOpen(true)}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-sm"
            >
              Otwórz okno wyglądu
            </button>
            <JarvisAppearanceDialog
              open={dialogOpen}
              onOpenChange={setDialogOpen}
              prefs={PREFS}
              onSave={() => setDialogOpen(false)}
            />
          </div>
          <div>
            <h2 className="mb-3 text-sm font-semibold">Wygląd asystenta</h2>
            <div className="max-w-[560px] rounded-xl border border-border bg-card p-5">
              <JarvisAppearanceForm prefs={PREFS} onSave={() => undefined} onCancel={() => undefined} />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

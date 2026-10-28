// „Wtyczka LinkedIn” (/wtyczka, 29.10.2026): ZIP do pobrania i instrukcja
// instalacji bez Chrome Web Store. ZIP (`public/wtyczka/nexus-linkedin.zip`)
// buduje `extension/scripts/pack.sh` — ma pole `key`, więc wtyczka ma na
// każdym laptopie to samo id, które NEXUS przepuszcza (LINKEDIN_EXTENSION_IDS).
// Strona jest za logowaniem (middleware), a połączenie wtyczki i tak wymaga
// konta NEXUSA z dostępem do rekrutacji.

import Link from "next/link";
import { Download, PlugZap, RefreshCw, TriangleAlert } from "lucide-react";

/** Wersja ZIP-a — ta sama co `extension/manifest.json` (pilnuje test). */
export const EXTENSION_VERSION = "1.0.3";
export const EXTENSION_ZIP_URL = "/wtyczka/nexus-linkedin.zip";

const INSTALL_STEPS: { title: string; body: React.ReactNode }[] = [
  {
    title: "Pobierz i rozpakuj",
    body: (
      <>
        Rozpakuj ZIP do folderu, którego nie będziesz usuwać, np.{" "}
        <code>Dokumenty/NEXUS-wtyczka</code>. Chrome czyta wtyczkę z tego folderu
        — po jego skasowaniu wtyczka zniknie. Windows: prawy klik → „Wyodrębnij
        wszystkie”. Mac: dwuklik na pliku.
      </>
    ),
  },
  {
    title: "Włącz tryb dewelopera w Chrome",
    body: (
      <>
        Wpisz w pasku adresu <code>chrome://extensions</code> i włącz „Tryb
        dewelopera” w prawym górnym rogu.
      </>
    ),
  },
  {
    title: "Wczytaj wtyczkę",
    body: (
      <>
        Kliknij „Wczytaj rozpakowane” i wskaż folder z kroku 1 — ten, w którym
        leży plik <code>manifest.json</code>. Na liście pojawi się „NEXUS —
        LinkedIn”.
      </>
    ),
  },
  {
    title: "Przypnij ikonę",
    body: <>Ikona puzzla obok paska adresu → pinezka przy „NEXUS — LinkedIn”.</>,
  },
  {
    title: "Połącz z NEXUSEM",
    body: (
      <>
        Otwórz LinkedIna, kliknij ikonę NEXUSA i „Zaloguj przez NEXUS”. Otworzy
        się karta NEXUSA, która po chwili pokaże „Połączono” i sama się zamknie.
      </>
    ),
  },
];

export function ExtensionInstallView() {
  return (
    <section className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <PlugZap className="h-4 w-4" aria-hidden="true" />
          Wtyczka Chrome
        </div>
        <h1 className="text-xl font-semibold text-foreground">Wtyczka LinkedIn</h1>
        <p className="text-sm text-muted-foreground">
          Panel NEXUSA na LinkedInie i w LinkedIn Recruiterze: czy osoba jest
          w NEXUSIE, kto ją prowadzi, czy wolno do niej pisać — i dodanie jej
          do rekrutacji jednym kliknięciem. Działa z kontem NEXUSA z dostępem do
          rekrutacji; bez niego wtyczka się nie połączy.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <a
          href={EXTENSION_ZIP_URL}
          download
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          Pobierz wtyczkę (ZIP, wersja {EXTENSION_VERSION})
        </a>
        <span className="text-xs text-muted-foreground">Chrome 116 lub nowszy</span>
      </div>

      <ol className="flex flex-col gap-3">
        {INSTALL_STEPS.map((step, i) => (
          <li key={step.title} className="flex gap-3 rounded-lg border border-border bg-card p-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-foreground">
              {i + 1}
            </span>
            <div className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">{step.title}</span>
              <span className="text-muted-foreground">{step.body}</span>
            </div>
          </li>
        ))}
      </ol>

      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 text-sm">
        <span className="flex items-center gap-2 font-medium text-foreground">
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Nowa wersja
        </span>
        <p className="text-muted-foreground">
          Gdy panel pokaże „Jest nowa wersja wtyczki”, pobierz ZIP stąd,
          rozpakuj go do tego samego folderu (zastąp pliki), a potem
          w <code>chrome://extensions</code> kliknij strzałkę odświeżenia przy
          „NEXUS — LinkedIn”. Połączenie z NEXUSEM zostaje.
        </p>
      </div>

      <div className="flex flex-col gap-2 rounded-lg bg-warning-muted p-3 text-sm text-warning-muted-foreground">
        <span className="flex items-center gap-2 font-medium">
          <TriangleAlert className="h-4 w-4" aria-hidden="true" />
          Gdy coś nie działa
        </span>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            „Ta wtyczka nie jest wtyczką NEXUSA” — masz starszą kopię spoza tej
            strony. Usuń ją w <code>chrome://extensions</code> i wczytaj ZIP stąd.
          </li>
          <li>
            Nie ma przełącznika „Tryb dewelopera” — komputer ma blokadę
            administratora. Napisz do administratora NEXUSA.
          </li>
          <li>
            Chrome po uruchomieniu pyta o wyłączenie wtyczek w trybie dewelopera
            — wybierz „Anuluj”, żeby wtyczka działała dalej.
          </li>
        </ul>
      </div>

      <p className="text-xs text-muted-foreground">
        Wtyczka czyta tylko otwartą stronę LinkedIna i tylko po kliknięciu, nic
        nie wysyła na LinkedInie.{" "}
        <Link href="/wtyczka/prywatnosc" className="text-primary underline underline-offset-4">
          Polityka prywatności wtyczki
        </Link>
      </p>
    </section>
  );
}

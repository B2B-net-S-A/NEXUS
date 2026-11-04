"use client";

/**
 * Ustawienia → Rekrutacja → „Stałe części ogłoszenia” (admin, Head of
 * Recruitment). „Co oferujemy”, etapy procesu, zdanie o firmie i dopisek do
 * tytułu wpisuje się raz — trafiają do każdego ogłoszenia na portale w tym
 * samym brzmieniu, rekruter ich nie przepisuje.
 *
 * Od 27.10.2026 tu stoi też opiekun konta Pracuj.pl — adresat maila „Wyślij do
 * Pracuj.pl” z okna „Ogłoszenie” (`ogloszenie-pracuj-mailem-do-opiekuna.md`).
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  jobAdApi,
  jobAdFixedBlocksQueryKey,
  linesToItems,
  type AdLang,
  type FixedBlocks,
  type TitleSuffix,
} from "@/lib/api/jobAd";

interface Draft {
  title_suffix: TitleSuffix;
  pl: { offer: string; process: string; about: string };
  en: { offer: string; process: string; about: string };
  caretaker: { name: string; email: string };
}

/** Skrzynka ogłoszeń Pracuj.pl — gdy serwer jeszcze nie zna opiekuna. */
const DEFAULT_CARETAKER_EMAIL = "ogloszenia@pracuj.pl";

const SUFFIX_OPTIONS: ReadonlyArray<{ value: TitleSuffix; label: string }> = [
  { value: "kmx", label: "(k/m/x) · (f/m/x)" },
  { value: "km", label: "(k/m) · (f/m)" },
  { value: "none", label: "bez dopisku" },
];
const LANG_OPTIONS: ReadonlyArray<{ value: AdLang; label: string }> = [
  { value: "pl", label: "Ogłoszenia po polsku" },
  { value: "en", label: "Ogłoszenia po angielsku" },
];
const SUFFIX_SAMPLE: Record<TitleSuffix, Record<AdLang, string>> = {
  kmx: { pl: " (k/m/x)", en: " (f/m/x)" },
  km: { pl: " (k/m)", en: " (f/m)" },
  none: { pl: "", en: "" },
};

function toDraft(blocks: FixedBlocks): Draft {
  const part = (lang: AdLang) => ({
    offer: blocks[lang].offer.join("\n"),
    process: blocks[lang].process.join("\n"),
    about: blocks[lang].about,
  });
  return {
    title_suffix: blocks.title_suffix,
    pl: part("pl"),
    en: part("en"),
    caretaker: {
      name: blocks.pracuj_caretaker?.name ?? "",
      email: blocks.pracuj_caretaker?.email ?? DEFAULT_CARETAKER_EMAIL,
    },
  };
}

function fromDraft(draft: Draft): FixedBlocks {
  const part = (lang: AdLang) => ({
    offer: linesToItems(draft[lang].offer),
    process: linesToItems(draft[lang].process),
    about: draft[lang].about.replace(/\s+/g, " ").trim(),
  });
  return {
    title_suffix: draft.title_suffix,
    pl: part("pl"),
    en: part("en"),
    pracuj_caretaker: {
      name: draft.caretaker.name.replace(/\s+/g, " ").trim(),
      email: draft.caretaker.email.trim(),
    },
  };
}

export default function JobAdFixedBlocksCard() {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [lang, setLang] = useState<AdLang>("pl");
  const [draft, setDraft] = useState<Draft | null>(null);

  const query = useQuery({
    queryKey: jobAdFixedBlocksQueryKey(),
    queryFn: jobAdApi.getFixedBlocks,
  });
  useEffect(() => {
    if (query.data) setDraft(toDraft(query.data));
  }, [query.data]);

  const save = useMutation({
    mutationFn: jobAdApi.saveFixedBlocks,
    onSuccess: (blocks) => {
      queryClient.setQueryData(jobAdFixedBlocksQueryKey(), blocks);
      // Otwarte okna ogłoszeń liczą teksty ze stałymi blokami po stronie serwera.
      void queryClient.invalidateQueries({ queryKey: ["job-ad"] });
      showSuccess("Stałe części ogłoszenia zapisane.");
    },
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się zapisać stałych części ogłoszenia.")),
  });

  const dirty =
    !!draft && !!query.data && JSON.stringify(fromDraft(draft)) !== JSON.stringify(query.data);
  const setCaretaker = (key: "name" | "email", value: string) =>
    setDraft((prev) =>
      prev ? { ...prev, caretaker: { ...prev.caretaker, [key]: value } } : prev,
    );
  const setPart = (key: "offer" | "process" | "about", value: string) =>
    setDraft((prev) => (prev ? { ...prev, [lang]: { ...prev[lang], [key]: value } } : prev));
  const preview = draft ? fromDraft(draft) : null;

  return (
    <div className="rounded-2xl border border-border bg-card p-6">
      {/* Tytuł ekranu rysuje strona Ustawień — tu tylko opis (20.10.2026). */}
      <p className="mb-5 text-sm text-muted-foreground">
        Wpisujesz raz. Trafiają do każdego ogłoszenia na Pracuj.pl i JustJoin.IT w tym samym
        brzmieniu — rekruter ich nie przepisuje.
      </p>

      {query.isError ? (
        <Alert
          variant="error"
          title="Nie udało się wczytać stałych części ogłoszenia"
          description={apiErrorMessage(query.error, "Spróbuj odświeżyć stronę.")}
        />
      ) : !query.isSuccess || !draft || !preview ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Wczytuję…
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <form
            className="flex flex-col gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate(fromDraft(draft));
            }}
          >
            <div className="flex flex-col gap-2">
              <p id="job-ad-suffix-label" className="text-sm font-semibold text-foreground">
                Dopisek do tytułu
              </p>
              <SegmentedRadio
                labelledBy="job-ad-suffix-label"
                size="sm"
                value={draft.title_suffix}
                options={SUFFIX_OPTIONS}
                onChange={(value) =>
                  setDraft((prev) => (prev ? { ...prev, title_suffix: value } : prev))
                }
              />
              <p className="text-xs text-muted-foreground">
                Pierwszy zapis dla ogłoszeń po polsku, drugi po angielsku. Tytuł, który już ma taki
                dopisek, zostaje bez zmian.
              </p>
            </div>

            <fieldset className="flex flex-col gap-2" data-testid="pracuj-caretaker">
              <legend className="text-sm font-semibold text-foreground">
                Opiekun konta Pracuj.pl
              </legend>
              <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-2">
                <label className="flex min-w-0 flex-col gap-1" htmlFor="pracuj-caretaker-name">
                  <span className="text-xs text-muted-foreground">Imię (do powitania)</span>
                  <Input
                    id="pracuj-caretaker-name"
                    value={draft.caretaker.name}
                    maxLength={60}
                    className="h-8 text-[13px]"
                    onChange={(e) => setCaretaker("name", e.target.value)}
                  />
                </label>
                <label className="flex min-w-0 flex-col gap-1" htmlFor="pracuj-caretaker-email">
                  <span className="text-xs text-muted-foreground">Adres e-mail</span>
                  <Input
                    id="pracuj-caretaker-email"
                    type="email"
                    value={draft.caretaker.email}
                    maxLength={254}
                    className="h-8 text-[13px]"
                    onChange={(e) => setCaretaker("email", e.target.value)}
                  />
                </label>
              </div>
              <p className="text-xs text-muted-foreground">
                Pracuj.pl nie ma u nas połączenia — Delivery Lead wysyła ogłoszenie na ten adres
                przyciskiem „Wyślij do Pracuj.pl”, ze swojej skrzynki.
              </p>
            </fieldset>

            <SegmentedRadio
              label="Język stałych części"
              size="sm"
              value={lang}
              options={LANG_OPTIONS}
              onChange={setLang}
            />

            <div className="flex flex-col gap-1.5">
              <label htmlFor="job-ad-offer" className="text-sm font-semibold text-foreground">
                Co oferujemy — w każdym ogłoszeniu
              </label>
              <Textarea
                id="job-ad-offer"
                aria-describedby="job-ad-offer-hint"
                rows={4}
                value={draft[lang].offer}
                onChange={(event) => setPart("offer", event.target.value)}
              />
              <p id="job-ad-offer-hint" className="text-xs text-muted-foreground">
                Jeden punkt w wierszu, najwyżej 8. Tryb pracy, start i długość projektu generator
                dopisuje sam z rekrutacji. Bez kwot i danych kontaktowych.
              </p>
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="job-ad-process" className="text-sm font-semibold text-foreground">
                Jak wygląda proces
              </label>
              <Textarea
                id="job-ad-process"
                aria-describedby="job-ad-process-hint"
                rows={3}
                value={draft[lang].process}
                onChange={(event) => setPart("process", event.target.value)}
              />
              <p id="job-ad-process-hint" className="text-xs text-muted-foreground">
                Jeden etap w wierszu, najwyżej 6.
              </p>
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="job-ad-about" className="text-sm font-semibold text-foreground">
                O firmie — jedno zdanie na końcu
              </label>
              <Textarea
                id="job-ad-about"
                rows={2}
                value={draft[lang].about}
                maxLength={600}
                onChange={(event) => setPart("about", event.target.value)}
              />
            </div>

            <div className="flex items-center gap-3">
              <Button type="submit" loading={save.isPending} disabled={!dirty}>
                Zapisz
              </Button>
              <span className="text-xs text-muted-foreground">
                Zmiana od razu obowiązuje we wszystkich oknach ogłoszeń — także już przygotowanych.
              </span>
            </div>
          </form>

          <aside
            aria-label="Podgląd"
            className="flex flex-col gap-3 self-start rounded-xl border border-border bg-muted/40 p-4 text-sm"
          >
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Tak trafia do ogłoszenia
            </p>
            <p className="font-semibold text-foreground">
              {lang === "en" ? "Senior Java Developer" : "Starszy Programista Java"}
              {SUFFIX_SAMPLE[draft.title_suffix][lang]}
            </p>
            {preview[lang].offer.length > 0 ? (
              <div>
                <p className="font-semibold text-foreground">
                  {lang === "en" ? "What we offer" : "Co oferujemy"}
                </p>
                <ul className="list-disc pl-5 text-foreground">
                  {preview[lang].offer.map((item, index) => (
                    <li key={`${index}-${item}`}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {preview[lang].process.length > 0 ? (
              <div>
                <p className="font-semibold text-foreground">
                  {lang === "en" ? "Recruitment process" : "Jak wygląda proces"}
                </p>
                <ol className="list-decimal pl-5 text-foreground">
                  {preview[lang].process.map((item, index) => (
                    <li key={`${index}-${item}`}>{item}</li>
                  ))}
                </ol>
              </div>
            ) : null}
            {preview[lang].about ? (
              <p className="text-muted-foreground">{preview[lang].about}</p>
            ) : null}
          </aside>
        </div>
      )}
    </div>
  );
}

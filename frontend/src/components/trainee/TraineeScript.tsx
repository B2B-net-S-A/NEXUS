/**
 * Prawa kolumna: skrypt rozmowy i „Pamiętaj” — tekst 1:1 z zatwierdzonej
 * makiety (Artur, 24.09.2026). Imię praktykanta wstawiamy w pierwsze zdanie.
 */
export function TraineeScript({ firstName }: { firstName: string | null }) {
  const who = firstName?.trim() || "…";
  const steps = [
    `„Dzień dobry, mówi ${who} z B2B.net. Mamy Pana CV w naszej bazie — czy ma Pan trzy minuty?”`,
    "„Czy szuka Pan teraz projektu albo będzie szukał w najbliższych miesiącach?”",
    "„Pracujemy wyłącznie na B2B. Pracuje Pan na B2B, a jeśli nie — czy byłby Pan gotów przejść?”",
    "„Jaka jest Pana minimalna stawka B2B netto?”",
    "„Gdyby trafił się projekt poniżej tej stawki — dzwonić profilaktycznie czy nie?”",
    "„Interesuje Pana tylko pełny etat, czy też projekty na część etatu (part-time)?”",
    "„Zdalnie, hybrydowo, w biurze — ile dni w biurze maksymalnie? A gdyby projekt wymagał więcej — dzwonić?”",
    "„Od kiedy mógłby Pan zacząć i jakich projektów szuka?”",
  ];
  return (
    <aside aria-label="Skrypt rozmowy" className="flex min-w-0 flex-col gap-4">
      <div className="rounded-xl border border-border bg-card p-4">
        <h2 className="text-sm font-semibold text-foreground">Skrypt rozmowy</h2>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-foreground">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <p className="mt-3 text-sm text-muted-foreground">
          Na koniec: „Dziękuję. Gdy pojawi się pasujący projekt, odezwie się do Pana nasz
          rekruter.”
        </p>
      </div>
      <div className="rounded-xl border border-border bg-muted p-4">
        <h2 className="text-sm font-semibold text-foreground">Pamiętaj</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-foreground">
          <li>
            Nie podawaj stawek ani nazw klientów — pytaj o minimalną stawkę i nie podpowiadaj
            kwot.
          </li>
          <li>
            Tylko etat i nie przejdzie na B2B? Zaznacz „Nie, tylko etat” i zapisz — osoba wypada
            z list i wyszukiwarki.
          </li>
          <li>Skąd mamy dane? Z CV, które kandydat przesłał nam wcześniej.</li>
          <li>
            Nie chce więcej telefonów? Wybierz „Niezainteresowany” — nikt z praktykantów już do
            niego nie zadzwoni.
          </li>
          <li>
            Pasuje idealnie do otwartej rekrutacji? Zapisz rozmowę i „Przekaż rekruterowi”.
          </li>
        </ul>
      </div>
    </aside>
  );
}

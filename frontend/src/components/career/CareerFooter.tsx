/** Stopka z danymi rejestrowymi administratora danych (B2B.NET S.A.). */
export const COMPANY_LEGAL_LINE =
  "Aleje Jerozolimskie 180, 02-486 Warszawa · Sąd Rejonowy dla m.st. Warszawy, XII Wydział Gospodarczy KRS · KRS: 0000387063 · NIP: 5711707392 · Kapitał zakładowy: 1 360 000,00 PLN, wpłacony w całości";

export function CareerFooter({
  rodoHref,
  hostLabel,
}: {
  rodoHref: string;
  /** Np. „kariera.dynaminds.pl/marta-n". */
  hostLabel: string;
}) {
  return (
    <footer className="kr-footer">
      <span className="kr-footer-top">
        <span className="kr-footer-brand">B2B.NET S.A.</span>
        <span>
          <a href={rodoHref} className="kr-footer-rodo">klauzula_rodo</a> · {hostLabel}
        </span>
      </span>
      <span>{COMPANY_LEGAL_LINE}</span>
    </footer>
  );
}

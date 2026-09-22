import type { ReactNode } from "react";

/** Nagłówek w dwóch tonach: biała pierwsza linia, bordo druga, blok-kursor. */
export function TwoToneTitle({
  first,
  second,
  className = "kr-title",
  as: Tag = "h1",
  inline = false,
}: {
  first: string;
  second: string;
  className?: string;
  as?: "h1" | "h2";
  /** Obie części w jednej linii („Dziękujemy, Jan."). */
  inline?: boolean;
}) {
  return (
    <Tag className={className}>
      {first ? (
        <>
          <span className="kr-title-a">{first}</span>
          {inline ? " " : <br />}
        </>
      ) : null}
      <span className="kr-title-b">{second}</span>
      <span className="kr-cursor" aria-hidden="true" />
    </Tag>
  );
}

/**
 * Hero: `$ whoami`, login rekrutera, polecenie `cat`, tytuł, linie pod nim.
 * Znaki `$` są dekoracją — czytnik ekranu czyta tekst polecenia bez nich.
 */
export function CareerHero({
  login,
  whoamiNote,
  catPath,
  title,
  children,
}: {
  login: string;
  whoamiNote: string;
  catPath: string;
  title: { first: string; second: string };
  /** Linie pod tytułem (polecenie deploy, komentarz). */
  children?: ReactNode;
}) {
  return (
    <div className="kr-hero">
      <span>
        <span className="kr-r" aria-hidden="true">
          ${" "}
        </span>
        whoami
      </span>
      <span className="kr-g">
        {login} — <span className="kr-r">{whoamiNote}</span>
      </span>
      <span>
        <span className="kr-r" aria-hidden="true">
          ${" "}
        </span>
        cat {catPath}
      </span>
      <TwoToneTitle first={title.first} second={title.second} />
      {children}
    </div>
  );
}

/** Linia polecenia z czerwonym `$`. */
export function Cmd({ children }: { children: ReactNode }) {
  return (
    <p className="kr-cmd">
      <b aria-hidden="true">$ </b>
      {children}
    </p>
  );
}

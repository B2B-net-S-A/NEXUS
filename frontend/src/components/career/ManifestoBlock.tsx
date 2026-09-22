import { Cmd } from "./CareerHero";

/** Blok manifestu Dynaminds. */
export function ManifestoBlock() {
  return (
    <section aria-label="Manifest">
      <Cmd>cat /etc/dynaminds/manifesto</Cmd>
      <p className="kr-manifesto">
        <span className="kr-title-a">Define</span>{" "}
        <span className="kr-title-b">tomorrow.</span>
      </p>
      <span className="kr-g" style={{ fontSize: 14 }}>
        <span className="kr-r" aria-hidden="true">
          ▶{" "}
        </span>
        we don&apos;t do &quot;standard&quot; · we set the standard
      </span>
    </section>
  );
}

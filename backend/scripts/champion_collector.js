/**
 * Collector profili Championa — biegnie w ZALOGOWANEJ karcie Traffita.
 *
 * Serwer NEXUS nie ma jak pobrać plików rekrutacji (Integration API Traffita
 * ich nie wystawia; sesyjny endpoint webowy wymaga cookies przeglądarki).
 * Ten skrypt domyka lukę: w karcie b2bnetwork.traffit.com pobiera pliki
 * profili i POST-uje je do /api/admin/champion-profiles/ingest.
 *
 * Użycie (operator / sesja Claude):
 *  1. Otwórz kartę na https://b2bnetwork.traffit.com (zalogowaną).
 *  2. Wklej ten skrypt do konsoli, ustawiwszy NEXUS_JWT (świeży token admina
 *     z localStorage zalogowanego nexus.dynaminds.pl).
 *  3. await runChampionCollector({ jwt: NEXUS_JWT })
 *
 * Skąd lista plików: mapa `localStorage["__nexus_champ_json"]`
 * ([{rid, entry, file, ext, name}]) ze skanu 08.2026. Świeży sync dla rid
 * spoza mapy: przemiata `/api/v2/recruitments/{rid}/files` od maxRid+1 w górę
 * (dławione — rate limit web-API ~2000 req; CONC 1, pauza 150 ms).
 *
 * Endpoint ingest jest idempotentny (pokryta oferta = skip bez kosztu AI),
 * więc powtórny bieg całości jest bezpieczny; diff przez /coverage sprawia,
 * że płaci się tylko za realne braki.
 */

async function runChampionCollector({
  jwt,
  nexusBase = "https://api.nexus.dynaminds.pl",
  scanNewFrom = null, // np. 4832 — skan świeżych rekrutacji; null = tylko mapa
  scanNewTo = null,
  pauseMs = 150,
  limit = null, // np. 20 dla próbki
} = {}) {
  if (!jwt) throw new Error("Podaj jwt (token admina NEXUS)");
  const H = { Authorization: `Bearer ${jwt}` };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // 1) Mapa znanych profili + pokrycie po stronie NEXUS.
  const map = JSON.parse(localStorage.getItem("__nexus_champ_json") || "[]");
  const covRes = await fetch(`${nexusBase}/api/admin/champion-profiles/coverage`, {
    headers: H,
  });
  if (!covRes.ok) throw new Error(`coverage ${covRes.status}`);
  const coverage = await covRes.json();
  const covered = new Set(coverage.covered_external_ids);
  let targets = map.filter((x) => !covered.has(x.rid));

  // 2) Opcjonalny skan świeżych rekrutacji (poza mapą).
  if (scanNewFrom) {
    const to = scanNewTo || scanNewFrom + 400;
    for (let rid = scanNewFrom; rid <= to; rid++) {
      if (covered.has(rid)) continue;
      try {
        const r = await fetch(`/api/v2/recruitments/${rid}/files`, {
          credentials: "include",
          headers: { Accept: "application/json" },
        });
        if (r.ok) {
          const files = await r.json();
          const items = Array.isArray(files) ? files : files.items || [];
          const champ = items.find((f) =>
            ((f.file && f.file.file_name) || f.file_name || "")
              .toLowerCase()
              .includes("champion"),
          );
          if (champ) {
            const fileId = (champ.file && champ.file.id) || champ.id;
            const ext =
              (champ.file && champ.file.extension) || champ.extension || "docx";
            const name =
              (champ.file && champ.file.file_name) || champ.file_name || "";
            targets.push({ rid, file: fileId, ext, name });
          }
        }
      } catch (e) {
        console.warn("scan rid", rid, String(e));
      }
      await sleep(pauseMs);
    }
  }

  if (limit) targets = targets.slice(0, limit);
  console.log(`cele: ${targets.length} (pokrytych: ${covered.size})`);

  // 3) Pobierz + wyślij, sekwencyjnie z pauzą (rate limit obu stron).
  const stats = { ok: 0, skipped: 0, no_job: 0, error: 0, rows: [] };
  for (const t of targets) {
    try {
      const fr = await fetch(`/api/file/fileContent/${t.file}`, {
        credentials: "include",
      });
      if (!fr.ok) throw new Error(`fileContent ${fr.status}`);
      const blob = await fr.blob();
      // 429 = rate limit — backoff i ponów (do 3 prób). FormData budowany
      // W KAŻDEJ próbie: spec nie gwarantuje ponownego odczytu body po
      // pierwszym wysłaniu (w niektórych silnikach retry poszedłby z pustym
      // multipartem i skończył 422).
      const buildForm = () => {
        const fd = new FormData();
        fd.append("file", blob, t.name || `champ_${t.rid}.${t.ext || "docx"}`);
        fd.append("external_rid", String(t.rid));
        fd.append("file_id", String(t.file));
        return fd;
      };
      let ir;
      for (let attempt = 0; ; attempt++) {
        ir = await fetch(`${nexusBase}/api/admin/champion-profiles/ingest`, {
          method: "POST",
          headers: H,
          body: buildForm(),
        });
        if (ir.status !== 429 || attempt >= 3) break;
        console.warn(`429 dla rid ${t.rid} — backoff ${(attempt + 1) * 20}s`);
        await sleep((attempt + 1) * 20_000);
      }
      const out = await ir.json().catch(() => ({ detail: `http ${ir.status}` }));
      const oc = out.outcome || out.detail || `http ${ir.status}`;
      stats.rows.push({ rid: t.rid, outcome: oc });
      if (oc === "ok") stats.ok++;
      else if (oc === "champion_skipped_nonempty") stats.skipped++;
      else if (oc === "no_job") stats.no_job++;
      else stats.error++;
      if (stats.rows.length % 10 === 0)
        console.log(`postęp ${stats.rows.length}/${targets.length}`, {
          ok: stats.ok,
          skipped: stats.skipped,
          no_job: stats.no_job,
          error: stats.error,
        });
    } catch (e) {
      stats.error++;
      stats.rows.push({ rid: t.rid, outcome: `exc:${String(e).slice(0, 80)}` });
    }
    await sleep(pauseMs);
  }
  console.log("KONIEC", stats);
  return stats;
}

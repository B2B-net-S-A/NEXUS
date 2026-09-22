/**
 * Paczka plików profili Championa — biegnie w ZALOGOWANEJ karcie Traffita.
 *
 * Następca `champion_collector.js` bez tokenu NEXUSA w przeglądarce: skrypt
 * niczego nie wysyła do NEXUSA, tylko zbiera pliki w jeden `.jsonl.gz`
 * zapisywany do Pobranych. Paczkę przetwarza w kontenerze backendu
 * `python -m scripts.champion_backfill --bundle … --merge-existing` (GPT Luna).
 *
 * Użycie (konsola na https://b2bnetwork.traffit.com, 22.09.2026):
 *   await championScan({ from: 4979, to: 38 })   // ~25 min, wznawialne
 *   await championBundle()                        // pobiera champion-bundle.jsonl.gz
 *
 * Wybór pliku: nazwa zawiera „champion" (w przeglądzie 09.2026 każdy profil
 * miał to słowo; reszta plików rekrutacji to formularze CV i SWZ). Przy kilku
 * wersjach wygrywa najnowsza (`created_at`, potem id pliku).
 */

async function championScan({ from = 4979, to = 38, pauseMs = 180 } = {}) {
  const key = "__nexus_champ_scan_v2";
  const files = JSON.parse(localStorage.getItem(key) || "{}");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  for (let rid = from; rid >= to; rid--) {
    if (files[rid]) continue;
    for (let attempt = 0; attempt < 5; attempt++) {
      const r = await fetch(`/api/v2/recruitments/${rid}/files`, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      if (r.status === 429) {
        await sleep(30000 * (attempt + 1));
        continue;
      }
      if (r.ok) {
        const j = await r.json();
        const items = Array.isArray(j) ? j : j.items || [];
        if (items.length)
          files[rid] = items.map((f) => ({
            entry: f.id,
            id: f.file && f.file.id,
            ext: f.file && f.file.extension,
            name: f.file && f.file.file_name,
            at: f.created_at,
          }));
      }
      break;
    }
    if (rid % 200 === 0) localStorage.setItem(key, JSON.stringify(files));
    await sleep(pauseMs);
  }
  localStorage.setItem(key, JSON.stringify(files));
  return Object.keys(files).length;
}

function championTargets(files) {
  const out = [];
  for (const [rid, list] of Object.entries(files)) {
    const champs = list
      .filter((f) => /champion/i.test(f.name || "") && /^(docx|pdf)$/i.test(f.ext || ""))
      .sort((a, b) => (a.at || "").localeCompare(b.at || "") || a.id - b.id);
    const pick = champs[champs.length - 1];
    if (pick) out.push({ rid: Number(rid), file: pick.id, name: pick.name });
  }
  return out;
}

async function championBundle({ pauseMs = 120, filename = "champion-bundle.jsonl.gz" } = {}) {
  const files = JSON.parse(localStorage.getItem("__nexus_champ_scan_v2") || "{}");
  const targets = championTargets(files);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const toB64 = (buf) => {
    let s = "";
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.length; i += 0x8000)
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };
  const lines = [];
  const failed = [];
  for (const t of targets) {
    const r = await fetch(`/api/file/fileContent/${t.file}`, { credentials: "include" });
    if (!r.ok) {
      failed.push({ rid: t.rid, status: r.status });
    } else {
      lines.push(JSON.stringify({ ...t, b64: toB64(await r.arrayBuffer()) }));
    }
    await sleep(pauseMs);
  }
  const gz = new Blob([lines.join("\n") + "\n"])
    .stream()
    .pipeThrough(new CompressionStream("gzip"));
  const blob = await new Response(gz).blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  return { targets: targets.length, bundled: lines.length, failed, bytes: blob.size };
}

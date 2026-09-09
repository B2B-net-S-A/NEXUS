/** Preserve an uncertain enqueue attempt across retries without storing CV content. */
const pending = new Map<string, string>();

async function digest(value: string | ArrayBuffer): Promise<string> {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)))
    .map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") return Object.fromEntries(
    Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]),
  );
  return value;
}

export async function withCvGenerationRequest<T>(path: string, data: object | FormData,
  send: (key: string) => Promise<T>): Promise<T> {
  let input: unknown = data;
  if (data instanceof FormData) {
    const entries = await Promise.all(Array.from(data.entries()).map(async ([key, value]) => [key,
      typeof value === "string" ? value : {name: value.name, type: value.type,
        size: value.size, sha256: await digest(await value.arrayBuffer())} ]));
    input = entries.sort(([a], [b]) => String(a).localeCompare(String(b)));
  }
  const storageKey = `nexus:cv-request:${await digest(JSON.stringify(canonical({path, input})))}`;
  let key = pending.get(storageKey);
  try { key ??= sessionStorage.getItem(storageKey) ?? undefined; } catch { /* Memory fallback. */ }
  key ??= crypto.randomUUID();
  pending.set(storageKey, key);
  try { sessionStorage.setItem(storageKey, key); } catch { /* Memory fallback. */ }
  const clear = () => {
    pending.delete(storageKey);
    try { sessionStorage.removeItem(storageKey); } catch { /* Memory fallback. */ }
  };
  try {
    const result = await send(key);
    clear();
    return result;
  } catch (error) {
    // A received 410 confirms that this attempt's result no longer exists.
    // Surface the error; only another deliberate click starts a new attempt.
    if (error && typeof error === "object" && "response" in error) {
      const response = error.response;
      if (response && typeof response === "object" && "status" in response && response.status === 410) clear();
    }
    throw error;
  }
}

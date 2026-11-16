// Jarvis na poligonie (ćwiczenie „Zapytaj Jarvisa o osobę z Tablicy”, 16.11.2026).
//
// Rozmowa z Jarvisem idzie natywnym `fetch` (strumień SSE, `lib/jarvis/stream.ts`),
// więc omija adapter axiosa — bez tego pytanie z poligonu trafiłoby do modelu
// i założyło prawdziwą rozmowę w bazie. W trybie poligonu `JarvisRoot` dostaje
// ten `fetch`: odpowiedź to stały tekst o osobie z Tablicy ćwiczebnej
// (`tools.ts` → `jarvisAnswer`), w tym samym formacie zdarzeń co serwer.

import { poligonStore } from "./adapter";

function frame(event: Record<string, unknown>): string {
  return `event: ${String(event.type)}\ndata: ${JSON.stringify(event)}\n\n`;
}

export const poligonJarvisFetch: typeof fetch = async (_input, init) => {
  let message = "";
  try {
    message = String((JSON.parse(String(init?.body ?? "{}")) as { message?: unknown }).message ?? "");
  } catch {
    message = "";
  }
  const store = await poligonStore();
  const markdown = store.jarvisAnswer(message);
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(frame({ type: "thinking", step: 1 })));
      controller.enqueue(encoder.encode(frame({ type: "message", markdown, final: true })));
      controller.enqueue(encoder.encode(frame({ type: "done" })));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
};

# PoC — prezentacja CLI na polskich sieciach

> Cel: zanim zainwestujemy ~20–24 dni w build własnego dialera, potwierdzić JEDYNE ryzyko, które bramkuje całą
> decyzję — **czy numer +48 kupiony u operatora wyświetla się na telefonie kandydata, czy „Numer nieznany"**.
> To rozstrzyga, którego operatora wybrać (a w szczególności czy najtańszy + natywny WebRTC Zadarma w ogóle wchodzi w grę).

Kontekst pełnej analizy: `~/.claude` rules + memory `project-telephony-research`. Skala docelowa: 20 → 40 rekruterów,
~126 000 min rozmów/mc, tylko połączenia (SMS zostaje na telefonach Play).

---

## Dlaczego to ryzyko #1

Polski mechanizm **„bezpieczna zatoka"** (UKE + 4 operatorzy, w mocy od 25.09.2024) blokuje albo anonimizuje
połączenia, których numer-CLI nie pochodzi z sieci operatora, który go nadał. Konsekwencja: legalnie da się
zaprezentować **tylko numer wydany/portowany u operatora, który zestawia połączenie**. Operator zagraniczny
(Zadarma, Twilio) może technicznie wstawić +48 w nagłówek, ale polskie sieci mogą i tak pokazać „Numer nieznany".
**Tego nie da się sprawdzić inaczej niż realnym telefonem.**

---

## Czego potrzeba (prerekwizyty — Wasza strona)

1. **Dane firmowe do KYC:** NIP/KRS + skan dokumentu osoby reprezentującej (operatorzy wymagają tego do wydania +48).
2. **4 telefony testowe** — po jednym na sieć: **Play, Orange, Plus, T-Mobile** (mogą być prywatne komórki zespołu).
   To na nich obserwujemy, co się wyświetla.
3. **Doładowanie prepaid** (kilkadziesiąt zł na operatora — testy to grosze, ale numer wymaga salda).
4. **~30 minut** jednej osoby na założenie triala + wydzwonienie 4 połączeń + wpis do karty wyników.

---

## Operatorzy do testu (w tej kolejności)

| Operator | Po co testujemy | Self-serve? | Stawka mobile | Natywny WebRTC |
|---|---|---|---|---|
| **Zadarma** | najtańszy (0,067 zł) + **natywny WebRTC = bez budowy SBC**; ALE CLI niepewny (operator zagraniczny) | ✅ online, szybkie | 0,067 zł | ✅ (omija SBC) |
| **Datera** | polski range-holder → **najbezpieczniejszy CLI**; pakiety 50k min ≈ 0,051 zł | ⚠️ przez sprzedaż | 0,09 zł / pakiety | ❌ (własny SBC) |
| **EasyCall** *(opcjonalnie)* | range-holder, 0,08 zł, zapas | ⚠️ kontrakt 24-mc | 0,08 zł | ❌ |

Minimalny sensowny test: **Zadarma + Datera**. Jeśli CLI Zadarmy przejdzie — mamy najtańszą opcję bez budowy SBC.
Jeśli nie — Datera jest bezpiecznym fallbackiem.

---

## Procedura (per operator)

1. **Załóż trial / konto firmowe**, przejdź KYC, **kup 1 numer +48** (najlepiej geograficzny — do CLI nie potrzeba komórkowego, bo SMS jest poza zakresem).
2. **Skonfiguruj wydzwanianie** jedną z dróg:
   - **A. Softphone (najszybciej):** Zoiper/Linphone → wpisz dane SIP konta (host/login/hasło z panelu operatora) → ustaw numer prezentowany = kupiony +48 → dzwoń ręcznie.
   - **B. API (powtarzalnie):** `place_test_calls.py` (Zadarma) — wydzwania automatycznie i zapisuje log.
3. **Zadzwoń na każdy z 4 telefonów** (Play/Orange/Plus/T-Mobile) i **zanotuj, co się wyświetliło** + jakość audio + opóźnienie.
4. **Test oddzwonienia:** z jednego z aparatów oddzwoń na prezentowany numer — sprawdź, czy połączenie wraca (inbound).
5. Wpisz wyniki do karty poniżej.

> Wskazówka: powtórz test o różnych porach (rano + popołudnie) — zatoka/filtry bywają zmienne.

---

## Karta wyników

Operator: ____________  Numer prezentowany (+48): ____________  Data/godz.: ____________

| Sieć odbiorcy | Wyświetlony CLI | „Numer nieznany"? | Jakość audio (1–5) | Opóźnienie zestawienia | Uwagi |
|---|---|---|---|---|---|
| Play | | ☐ | | | |
| Orange | | ☐ | | | |
| Plus | | ☐ | | | |
| T-Mobile | | ☐ | | | |
| **Oddzwonienie (inbound)** | działa? ☐ tak ☐ nie | — | | | |

---

## Kryterium decyzji (go / no-go)

- **CLI wyświetla się na ≥3/4 sieci, audio ≥4/5, inbound działa** → ✅ operator przechodzi.
- **Zadarma przeszła** → rekomendacja: Zadarma (natywny WebRTC → **kasujemy ~7–9 dni budowy SBC**, najtańsze minuty).
- **Zadarma nie przeszła, Datera przeszła** → Datera + własny FreeSWITCH/jambonz (CLI bezpieczny, pakiety minut).
- **Obie zawiodły na CLI** → eskalacja do range-holdera kontraktowego (Netia / T-Mobile / Orange biznes) z SLA na prezentację numeru.

Wynik wpisać do `project-telephony-research` (memory) i ruszać z planem wdrożenia dla zwycięskiego operatora.

---

## Pliki

- `place_test_calls.py` — automatyczne wydzwanianie testowe przez API Zadarmy (auth HMAC, log wyników). Wymaga
  `ZADARMA_API_KEY` / `ZADARMA_API_SECRET` w env. Dla Datery/EasyCall użyj drogi A (softphone).

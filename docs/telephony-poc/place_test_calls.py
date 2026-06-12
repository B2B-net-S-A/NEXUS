"""PoC CLI test — automatyczne wydzwanianie przez API Zadarmy.

Cel: zestawić połączenie z kupionego numeru +48 na każdy z 4 telefonów testowych
(Play/Orange/Plus/T-Mobile) i ręcznie odnotować, CO WYŚWIETLA SIĘ na ekranie odbiorcy.
To weryfikuje „bezpieczną zatokę" — jedyne ryzyko, którego nie da się sprawdzić inaczej
niż realnym aparatem.

Mechanika Zadarmy: metoda callback dzwoni najpierw na ``from`` (telefon operatora testu —
odbierasz), a potem łączy z ``to`` (telefon testowy danej sieci), prezentując numer konta.
Obserwator trzymający aparat ``to`` notuje wyświetlony CLI.

Wymaga w środowisku:
    ZADARMA_API_KEY, ZADARMA_API_SECRET   (panel Zadarma → Ustawienia → API)

Użycie:
    export ZADARMA_API_KEY=... ZADARMA_API_SECRET=...
    python place_test_calls.py --from +48XXXXXXXXX \\
        --play +48... --orange +48... --plus +48... --tmobile +48...

Dla Datery/EasyCall (brak tak czystego API) użyj softphone'a (Zoiper) i karty wyników w README.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("cli-poc")

API_BASE = "https://api.zadarma.com"
CALLBACK_METHOD = "/v1/request/callback/"


@dataclass(frozen=True)
class ZadarmaCredentials:
    """Klucze API Zadarmy (nigdy nie hardkodować — tylko z env)."""

    key: str
    secret: str

    @staticmethod
    def from_env() -> "ZadarmaCredentials":
        key = os.environ.get("ZADARMA_API_KEY")
        secret = os.environ.get("ZADARMA_API_SECRET")
        if not key or not secret:
            raise SystemExit("Brak ZADARMA_API_KEY / ZADARMA_API_SECRET w środowisku.")
        return ZadarmaCredentials(key=key, secret=secret)


def _sign(creds: ZadarmaCredentials, method: str, params: dict[str, str]) -> tuple[str, str]:
    """Zwraca (query_string, Authorization) zgodnie ze schematem auth Zadarmy.

    signature = base64( hex( hmac_sha1( method + query + md5(query), secret ) ) )
    """
    query = urllib.parse.urlencode(sorted(params.items()))
    md5_hex = hashlib.md5(query.encode()).hexdigest()  # noqa: S324 - wymóg API Zadarmy
    raw = f"{method}{query}{md5_hex}".encode()
    digest_hex = hmac.new(creds.secret.encode(), raw, hashlib.sha1).hexdigest()
    signature = base64.b64encode(digest_hex.encode()).decode()
    return query, f"{creds.key}:{signature}"


def place_callback(creds: ZadarmaCredentials, caller: str, callee: str) -> str:
    """Zestawia połączenie callback (from=caller, to=callee). Zwraca surową odpowiedź API."""
    params = {"from": caller, "to": callee}
    query, authorization = _sign(creds, CALLBACK_METHOD, params)
    request = urllib.request.Request(
        url=f"{API_BASE}{CALLBACK_METHOD}?{query}",
        headers={"Authorization": authorization},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - stały host API
        return response.read().decode()


def run(caller: str, targets: dict[str, str]) -> None:
    creds = ZadarmaCredentials.from_env()
    results: list[dict[str, str]] = []
    for network, number in targets.items():
        if not number:
            continue
        logger.info("Dzwonię na %s (%s) — odbierz %s, potem zobacz ekran %s...", network, number, caller, network)
        try:
            api_response = place_callback(creds, caller, number)
            logger.info("API: %s", api_response)
        except Exception as exc:  # noqa: BLE001 - PoC: chcemy zobaczyć każdy błąd
            logger.error("Błąd zestawienia: %s", exc)
            api_response = f"ERROR: {exc}"
        displayed = input(f"  Co wyświetliło się na {network}? (numer / 'nieznany' / 'brak'): ").strip()
        audio = input("  Jakość audio 1–5: ").strip()
        results.append(
            {
                "siec": network,
                "wybrany_numer": number,
                "wyswietlony_cli": displayed,
                "audio_1_5": audio,
                "api_response": api_response,
            }
        )

    out_path = "cli_test_results.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["siec", "wybrany_numer", "wyswietlony_cli", "audio_1_5", "api_response"])
        writer.writeheader()
        writer.writerows(results)
    logger.info("Zapisano wyniki do %s", out_path)
    passed = sum(1 for r in results if r["wyswietlony_cli"] not in {"nieznany", "brak", ""})
    logger.info("CLI wyświetlony na %d/%d sieci. Próg go: ≥3/4.", passed, len(results))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PoC test prezentacji CLI (Zadarma).")
    parser.add_argument("--from", dest="caller", required=True, help="Telefon operatora testu (odbierasz pierwszy).")
    parser.add_argument("--play", default="", help="Numer testowy w sieci Play.")
    parser.add_argument("--orange", default="", help="Numer testowy w sieci Orange.")
    parser.add_argument("--plus", default="", help="Numer testowy w sieci Plus.")
    parser.add_argument("--tmobile", default="", help="Numer testowy w sieci T-Mobile.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(
        caller=args.caller,
        targets={"Play": args.play, "Orange": args.orange, "Plus": args.plus, "T-Mobile": args.tmobile},
    )

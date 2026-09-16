"""Cliente de prueba del agente IA local (MVP, fácil de eliminar).

Uso (con el agente en marcha):
    uv run python scripts/test_local_ai_agent.py [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

TEXT_1 = "De contado, la pago de contado."
TEXT_2 = "¿Cuánto queda la cuota?"
REQUEST_TIMEOUT = 300.0


def _call(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prueba del agente IA local")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    base = f"http://127.0.0.1:{args.port}"

    t0 = time.perf_counter()
    status, health = _call("GET", f"{base}/health")
    print(f"[health] http={status} latencia_ms={int((time.perf_counter()-t0)*1000)}")
    print(f"  conexion con agente: {'OK' if health.get('status') == 'ok' else 'FALLO'}")
    print(f"  conexion con Ollama: {health.get('ollama')}")
    print(f"  modelo: {health.get('model')}")

    for text in (TEXT_1, TEXT_2):
        t0 = time.perf_counter()
        status, body = _call("POST", f"{base}/analyze", {"text": text})
        latency_ms = int((time.perf_counter() - t0) * 1000)
        print(f"[analyze] http={status} latencia_ms={latency_ms}")
        print(f"  texto: {text}")
        print(f"  modelo utilizado: {body.get('model')}")
        print(f"  respuesta: {str(body.get('result') or body.get('error'))[:400]}")
        if not body.get("ok"):
            raise SystemExit("ERROR: /analyze devolvió ok=false")
    print("PRUEBA OK: cliente -> agente -> Ollama -> agente -> cliente")


if __name__ == "__main__":
    main()

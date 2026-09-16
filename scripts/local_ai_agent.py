"""Agente IA local (prueba de arquitectura MVP, fácil de eliminar).

Flujo: cliente HTTP local -> este agente (127.0.0.1) -> Ollama -> respuesta.

Uso:
    uv run python scripts/local_ai_agent.py [--port 8765]
        [--ollama-url http://127.0.0.1:11434] [--model qwen2.5:3b]

Seguridad: solo escucha en loopback (127.0.0.1). No expone nada a la red.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

DEFAULT_PORT = 8765
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"
REQUEST_TIMEOUT = 300.0

# MVP prueba 2/3: orígenes explícitos de prueba (nunca "*").
DEFAULT_CORS_ORIGINS = "http://127.0.0.1:8080"


class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    """Solo PNA (Chrome 130+): si el preflight trae
    `Access-Control-Request-Private-Network`, responde
    `Access-Control-Allow-Private-Network: true` para orígenes permitidos.
    El resto de preflights los sigue atendiendo CORSMiddleware."""

    def __init__(self, app, allow_origins: list[str]) -> None:
        super().__init__(app)
        self.allow_origins = allow_origins

    async def dispatch(self, request, call_next):
        if (request.method == "OPTIONS" and
                "access-control-request-private-network" in request.headers):
            origin = request.headers.get("origin")
            if origin in self.allow_origins:
                return Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Private-Network": "true",
                        "Access-Control-Allow-Methods": "GET, POST",
                        "Access-Control-Allow-Headers": "Content-Type",
                        "Access-Control-Max-Age": "600",
                    },
                )
            return Response(status_code=403, content="origen no permitido")
        return await call_next(request)


class AnalyzeRequest(BaseModel):
    # Modo simple (página de prueba): prompt plano -> /api/generate.
    text: str | None = None
    # Modo extracción (LocalExtractor): mensajes estilo chat + JSON schema.
    messages: list[dict] | None = None
    format: dict | None = None
    model: str | None = None


def build_app(ollama_url: str, model: str,
              cors_origins: list[str] | None = None) -> FastAPI:
    origins = cors_origins or [DEFAULT_CORS_ORIGINS]
    app = FastAPI(title="Local AI Agent (MVP)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    # Se registra después para que se ejecute antes que CORSMiddleware.
    app.add_middleware(PrivateNetworkAccessMiddleware, allow_origins=origins)
    config = {"ollama_url": ollama_url.rstrip("/"), "model": model}

    def _ollama_get(path: str) -> Any:
        request = urllib.request.Request(
            f"{config['ollama_url']}{path}", method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _ollama_generate(prompt: str) -> str:
        payload = json.dumps(
            {"model": config["model"], "prompt": prompt,
             "stream": False}).encode("utf-8")
        request = urllib.request.Request(
            f"{config['ollama_url']}/api/generate",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        text = (data.get("response") or "").strip()
        if not text:
            raise RuntimeError("Ollama devolvió una respuesta vacía")
        return text

    def _ollama_chat(messages: list[dict], fmt: dict | None,
                     model: str | None) -> str:
        """Modo chat (extracción): reenvía mensajes; `format` opcional fuerza
        la salida JSON. Devuelve el contenido del asistente."""
        payload_dict: dict = {
            "model": model or config["model"],
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0},
        }
        if fmt is not None:
            payload_dict["format"] = fmt
        payload = json.dumps(payload_dict).encode("utf-8")
        request = urllib.request.Request(
            f"{config['ollama_url']}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = (data.get("message", {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("Ollama devolvió una respuesta vacía")
        return content

    @app.get("/health")
    def health() -> dict:
        try:
            _ollama_get("/api/tags")
            ollama_ok: bool | str = True
        except Exception as exc:  # noqa: BLE001 - el agente sigue vivo
            ollama_ok = f"no disponible: {type(exc).__name__}"
        return {"status": "ok", "ollama": ollama_ok, "model": config["model"]}

    @app.post("/analyze")
    def analyze(body: AnalyzeRequest) -> dict:
        if body.messages:
            try:
                result = _ollama_chat(body.messages, body.format, body.model)
            except Exception as exc:  # noqa: BLE001 - error visible, no oculto
                return {"ok": False, "model": body.model or config["model"],
                        "error": f"{type(exc).__name__}: {exc}"}
            return {"ok": True, "model": body.model or config["model"],
                    "result": result}
        if body.text and body.text.strip():
            try:
                result = _ollama_generate(body.text)
            except Exception as exc:  # noqa: BLE001 - error visible, no oculto
                return {"ok": False, "model": config["model"],
                        "error": f"{type(exc).__name__}: {exc}"}
            return {"ok": True, "model": config["model"], "result": result}
        return {"ok": False, "model": config["model"],
                "error": "request debe incluir 'text' o 'messages'"}

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local AI Agent (MVP)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--cors-origins", default=DEFAULT_CORS_ORIGINS,
        help="Orígenes permitidos separados por coma (nunca '*').")
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Por seguridad, el agente solo escucha en loopback.")

    import uvicorn

    origins = [o.strip() for o in args.cors_origins.split(",") if o.strip()]
    if "*" in origins:
        raise SystemExit("No se permite Access-Control-Allow-Origin: *.")
    uvicorn.run(build_app(args.ollama_url, args.model, origins),
                host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

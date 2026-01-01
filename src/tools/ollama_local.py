import json
from typing import Any, Dict, Optional

import requests


def call_local_ollama(
    prompt: str,
    model: str = "qwen3:0.6b",
    host: str = "http://127.0.0.1:11434",
    stream: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Call a local Ollama-style endpoint at /api/generate.

    Args:
        prompt: The prompt to send.
        model: Model name (e.g., 'qwen3:0.6b').
        host: Base URL of the local server (default http://127.0.0.1:11434).
        stream: Whether to request streaming from the server.
        options: Extra options passed through to the backend.

    Returns:
        The generated text response from the local model.
    """
    url = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
    }
    if options:
        payload["options"] = options

    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return f"[call_local_ollama] request failed: {exc}"

    # Ollama /api/generate responses may contain 'response' or 'output' fields
    text = data.get("response") or data.get("output") or data
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    return text.strip()

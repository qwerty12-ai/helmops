"""Optional local LLM (Ollama, free). Returns None on any problem so callers fall back to rules."""
import json
import httpx
from . import config


def ollama_json(prompt: str, timeout: float = 60):
    if not config.OLLAMA_MODEL:
        return None
    try:
        r = httpx.post(
            f"{config.OLLAMA_URL}/api/generate",
            json={"model": config.OLLAMA_MODEL, "prompt": prompt, "format": "json",
                  "stream": False, "options": {"temperature": 0}},
            timeout=timeout,
        )
        data = json.loads(r.json()["response"])
        return data if isinstance(data, dict) else None
    except Exception:
        return None

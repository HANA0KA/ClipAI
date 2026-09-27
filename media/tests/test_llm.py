"""Selección de proveedor LLM y cadena de modelos (sin red)."""
import json

import pytest
from pydantic import BaseModel

from media.config import reset_settings
from media.services import llm as llm_mod


class Item(BaseModel):
    start: float
    end: float


@pytest.fixture()
def clean_env(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_MODEL", "GEMINI_API_KEY", "VERTEX_PROJECT_ID", "VERTEX_LOCATION",
              "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SERVICE_ACCOUNT_FILE"):
        monkeypatch.setenv(k, "")
    monkeypatch.setattr(llm_mod, "_UNAVAILABLE", set())
    monkeypatch.setattr(llm_mod, "_GLOBAL_ONLY", set())
    reset_settings()
    yield monkeypatch
    reset_settings()


def test_provider_priority(clean_env):
    assert llm_mod.LLM().provider == "none"
    clean_env.setenv("GEMINI_API_KEY", "k")
    reset_settings()
    assert llm_mod.LLM().provider == "gemini"
    clean_env.setenv("VERTEX_PROJECT_ID", "p")
    clean_env.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"project_id": "p"}')
    reset_settings()
    assert llm_mod.LLM().provider == "vertex"  # Vertex gana a la API key
    clean_env.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    clean_env.setenv("LLM_MODEL", "qwen2.5:7b")
    reset_settings()
    assert llm_mod.LLM().provider == "openai"  # un servidor local explícito gana a todo


class _Resp:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, location, log):
        self.location, self.log = location, log

    def generate_content(self, model, contents, config):
        self.log.append((self.location, model))
        if model.startswith("gemini-3") and self.location != "global":
            raise RuntimeError("404 NOT_FOUND. Publisher model `gemini-3.5-flash` was not found")
        if model == "gemini-2.5-flash":
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota")
        return _Resp(json.dumps([{"start": 1, "end": 40}]))


def test_vertex_regional_404_retries_on_global(clean_env, tmp_path):
    sa = tmp_path / "sa.json"
    sa.write_text('{"project_id": "p"}')
    clean_env.setenv("VERTEX_PROJECT_ID", "p")
    clean_env.setenv("VERTEX_LOCATION", "us-central1")
    clean_env.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(sa))
    clean_env.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    clean_env.setenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash")
    reset_settings()
    calls = []
    llm = llm_mod.LLM(sleep_fn=lambda s: None)
    assert llm.provider == "vertex" and llm.models == ["gemini-2.5-flash", "gemini-3.5-flash"]
    clean_env.setattr(llm, "_gemini_client", lambda model=None: type("C", (), {
        "models": _Models("global" if model in llm_mod._GLOBAL_ONLY else "us-central1", calls)})())
    items = llm.generate_list("prompt", Item)
    assert items[0].end == 40 and llm.last_model == "gemini-3.5-flash"
    # 2.5-flash: cuota → siguiente modelo; 3.5-flash: 404 regional → reintento en global.
    assert calls == [("us-central1", "gemini-2.5-flash"), ("us-central1", "gemini-3.5-flash"),
                     ("global", "gemini-3.5-flash")]
    assert "gemini-3.5-flash" in llm_mod._GLOBAL_ONLY and not llm_mod._UNAVAILABLE

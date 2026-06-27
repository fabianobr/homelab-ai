"""
OllamaFlushVRAM — descarrega os modelos do Ollama para liberar VRAM antes de
workflows pesados (ex.: geração de vídeo LTX) numa GPU compartilhada.

Contexto: ComfyUI e Ollama dividem os 16GB da NVIDIA GPU. Quando o Ollama tem
um LLM carregado (~5-9GB) e o ComfyUI tenta rodar um modelo de vídeo + VAE
decode, a soma estoura a VRAM e o ComfyUI dá CUDA OOM. Este node chama a API do
Ollama (keep_alive=0) para descarregar os modelos e espera a VRAM ser liberada
antes de devolver o controle ao grafo.

Sem dependências externas — usa só a stdlib (urllib).
"""

import json
import time
import urllib.error
import urllib.request


# Tipo "wildcard": aceita/produz qualquer tipo, permitindo inserir o node em
# qualquer ponto do grafo como passthrough (a saída devolve a entrada).
class AnyType(str):
    def __ne__(self, other):
        return False


any_type = AnyType("*")

DEFAULT_OLLAMA_URL = "http://ollama:11434"


def _http_get(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(url, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _list_loaded_models(base_url, timeout):
    """Retorna a lista de nomes de modelos atualmente carregados no Ollama."""
    info = _http_get(f"{base_url}/api/ps", timeout=timeout)
    return [m["name"] for m in info.get("models", [])]


def _unload_model(base_url, name, timeout):
    """Pede ao Ollama para descarregar um modelo (keep_alive=0, sem gerar)."""
    _http_post(
        f"{base_url}/api/generate",
        {"model": name, "keep_alive": 0},
        timeout=timeout,
    )


def flush_ollama(base_url, wait_seconds):
    """
    Descarrega todos os modelos do Ollama e espera (até wait_seconds) a VRAM
    ser liberada. Retorna uma string de status legível.

    Falhas de rede com o Ollama NÃO derrubam o workflow: se o Ollama está
    inacessível/parado, não há VRAM dele para liberar, então seguimos em frente
    com um aviso explícito no status (sem mascarar erros inesperados de outro
    tipo, que são relançados).
    """
    base_url = base_url.rstrip("/")
    try:
        loaded = _list_loaded_models(base_url, timeout=5)
    except urllib.error.URLError as exc:
        msg = f"[OllamaFlushVRAM] Ollama inacessível em {base_url} ({exc}); nada a liberar."
        print(msg)
        return msg

    if not loaded:
        msg = "[OllamaFlushVRAM] Nenhum modelo carregado no Ollama; VRAM já livre."
        print(msg)
        return msg

    print(f"[OllamaFlushVRAM] Descarregando do Ollama: {', '.join(loaded)}")
    for name in loaded:
        try:
            _unload_model(base_url, name, timeout=30)
        except urllib.error.URLError as exc:
            print(f"[OllamaFlushVRAM] Aviso: falha ao descarregar {name} ({exc}).")

    # Espera o Ollama efetivamente soltar os modelos (libera a VRAM).
    deadline = time.time() + max(0.0, wait_seconds)
    remaining = loaded
    while time.time() < deadline:
        try:
            remaining = _list_loaded_models(base_url, timeout=5)
        except urllib.error.URLError:
            remaining = []
        if not remaining:
            break
        time.sleep(0.5)

    # Limpa o cache de alocador do PyTorch para tornar a VRAM liberada utilizável.
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as exc:  # noqa: BLE001 - best effort, não deve quebrar o flush
        print(f"[OllamaFlushVRAM] Aviso: empty_cache falhou ({exc}).")

    if remaining:
        msg = (
            f"[OllamaFlushVRAM] Timeout: ainda carregados após {wait_seconds}s: "
            f"{', '.join(remaining)}."
        )
    else:
        msg = f"[OllamaFlushVRAM] VRAM liberada (descarregados: {', '.join(loaded)})."
    print(msg)
    return msg


class OllamaFlushVRAM:
    """
    Descarrega os modelos do Ollama para liberar VRAM antes do ComfyUI alocar a GPU.

    Insira como passthrough no início do trecho pesado: ligue qualquer fio
    (MODEL, CONDITIONING, LATENT, etc.) na entrada `passthrough` e use a saída no
    lugar — o flush executa quando este node roda. Para máximo benefício, plugue
    o mais cedo possível (antes da amostragem), assim a diffusion e o VAE decode
    rodam com a VRAM inteira.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ollama_url": ("STRING", {"default": DEFAULT_OLLAMA_URL}),
                "wait_seconds": (
                    "FLOAT",
                    {"default": 15.0, "min": 0.0, "max": 120.0, "step": 1.0},
                ),
            },
            "optional": {
                "passthrough": (any_type,),
            },
        }

    RETURN_TYPES = (any_type, "STRING")
    RETURN_NAMES = ("passthrough", "status")
    FUNCTION = "run"
    CATEGORY = "utils/vram"
    OUTPUT_NODE = False

    def run(self, ollama_url, wait_seconds, passthrough=None):
        status = flush_ollama(ollama_url, wait_seconds)
        return (passthrough, status)

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        # Sempre reexecuta: o estado da VRAM/Ollama muda entre runs.
        return float("nan")


NODE_CLASS_MAPPINGS = {"OllamaFlushVRAM": OllamaFlushVRAM}
NODE_DISPLAY_NAME_MAPPINGS = {"OllamaFlushVRAM": "Ollama Flush VRAM"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

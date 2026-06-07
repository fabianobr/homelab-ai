# ComfyUI-OllamaFlushVRAM

Custom node que descarrega os modelos do Ollama para **liberar VRAM** antes de
workflows pesados do ComfyUI (ex.: geração de vídeo LTX) numa GPU compartilhada.

## Por quê

ComfyUI e Ollama dividem os 16GB da NVIDIA GPU. Com um LLM carregado no Ollama
(~5-9GB), o ComfyUI fica sem VRAM para o modelo de vídeo + VAE decode e dá
`CUDA out of memory`. Este node chama a API do Ollama (`keep_alive=0`) para
descarregar os modelos e espera a VRAM ser liberada antes de seguir o grafo.

## Uso

1. Adicione o node **Ollama Flush VRAM** (categoria `utils/vram`).
2. Ligue qualquer fio (MODEL, CONDITIONING, LATENT, IMAGE...) na entrada
   `passthrough` e use a saída `passthrough` no lugar. O flush dispara quando o
   node executa.
3. **Plugue o mais cedo possível** (antes da amostragem) para a diffusion e o
   VAE decode rodarem com a VRAM inteira.

### Parâmetros
- `ollama_url` (padrão `http://ollama:11434`) — endereço do Ollama. Como ComfyUI
  e Ollama estão na mesma rede Docker, o padrão funciona direto.
- `wait_seconds` (padrão 15) — tempo máximo aguardando o Ollama soltar os modelos.

### Saídas
- `passthrough` — devolve a entrada, intacta.
- `status` — string com o resultado (descarregados / nada a liberar / timeout).

## Instalação / sincronização
Esta é a **cópia versionada** (backup/fonte). A cópia **ativa** que o container
ComfyUI carrega fica no bind mount:
`/home/user/AI/ComfyUI/custom_nodes/ComfyUI-OllamaFlushVRAM/`.

Ao editar aqui, sincronize para a cópia ativa e reinicie o ComfyUI:
```bash
cp -r docker/comfyui/custom_nodes/ComfyUI-OllamaFlushVRAM \
      /home/user/AI/ComfyUI/custom_nodes/
docker compose -f docker/docker-compose.yml restart comfyui
```

## Notas
- Sem dependências externas (usa só a stdlib `urllib`).
- Se o Ollama estiver inacessível/parado, o node apenas avisa e segue (não há
  VRAM dele para liberar) — não derruba o workflow.
- Defesa complementar: `OLLAMA_KEEP_ALIVE=30s` no docker-compose faz o Ollama
  soltar a VRAM sozinho quando ocioso.

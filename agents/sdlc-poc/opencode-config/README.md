## Workflow: Discovery → Spec → Code

The SDLC PoC uses two n8n workflows and a manual handoff step:

1. **Discovery (Workflow 1):** POST to `/webhook/sdlc-poc-chat` with `{"chatInput": "...", "messages": []}`. Have a multi-turn conversation until you're ready to generate the spec, then send `"chatInput": "gerar spec"`.

2. **Spec handoff (manual):** The response will contain a spec wrapped between `---SPEC-START---` and `---SPEC-END---`. Copy the text between those markers.

3. **Code gen (Workflow 2):** POST to `/webhook/sdlc-poc-spec-to-code` with `{"spec": "<copied spec text>"}`. Returns `{files: [...], fileCount: N}`.

4. **OpenCode (optional):** Alternatively, paste the spec into OpenCode TUI and let it implement directly in your codebase.

# OpenCode Configuration

This directory contains an example configuration for OpenCode v1.17.8 with Ollama integration.

## Setup Instructions

### 1. Copy and Configure

```bash
cp opencode.jsonc.example ~/.config/opencode/opencode.jsonc
```

**Important:** OpenCode v1.17.8 uses the JSONC format (`opencode.jsonc`), NOT `config.json`. The filename and location matter:
- **Target filename:** `~/.config/opencode/opencode.jsonc` (JSONC format)
- **Target directory:** `~/.config/opencode/`

### 2. Verify the Configuration

After placing the config, verify it's loaded correctly:

```bash
opencode debug config
```

This should display your configuration and confirm that the Ollama provider is available.

If `opencode` command is not found, use the full path:

```bash
/home/fabiano/.opencode/bin/opencode debug config
```

Or source bashrc to update your PATH:

```bash
source ~/.bashrc
```

### 3. Verify Ollama is Running

Ensure your Ollama instance is running and has the required model. Test with:

```bash
curl http://localhost:11434/api/tags
```

This should list available models, including `qwen2.5-coder:32b`:

```json
{
  "models": [
    {
      "name": "qwen2.5-coder:32b",
      ...
    }
  ]
}
```

If the model is not available, pull it:

```bash
ollama pull qwen2.5-coder:32b
```

## Configuration Details

The example config includes:

- **Provider:** Ollama Local
- **API Endpoint:** `http://localhost:11434/v1` (OpenAI-compatible API)
- **Model:** `qwen2.5-coder:32b` (high-capacity code generation)
- **SDK:** Uses `@ai-sdk/openai-compatible` for API communication

## Como usar o opencode com a POC SDLC

O opencode pode substituir o WF3+WF4 (Developer Agent + Fix Agent) ou ser usado para interpretar o pipeline existente.

### Modo A — opencode como Developer Agent (substitui WF3+WF4)

Gere a spec via WF1 (Discovery), copie o bloco entre `---SPEC-START---` e `---SPEC-END---`, e implemente direto no opencode. Ele escreve arquivos, roda pytest e itera automaticamente.

```bash
# Modo interativo (TUI):
cd "$(git rev-parse --show-toplevel)"
opencode
# Cole a spec no chat e peça: "Implemente como FastAPI com TDD, gere test_main.py primeiro"

# Modo headless:
opencode run \
  "Implemente a spec abaixo em FastAPI: models.py, routes.py, main.py.
   Gere test_main.py primeiro (TDD). Rode pytest e corrija até 100% passing.
   <spec>" \
  --model ollama/qwen3-coder:30b
```

### Modo B — opencode como driver dos scripts existentes

```bash
opencode run \
  "Execute ./agents/sdlc-poc/tests/generate-tdd.sh /tmp/spec.md /tmp/out,
   leia o resultado do pytest e explique o que falhou e por quê" \
  --model ollama/qwen3-coder:30b
```

---

## Troubleshooting

- **Config not loading:** Ensure the file is at `~/.config/opencode/opencode.jsonc` (case-sensitive, JSONC format)
- **Ollama not responding:** Verify Ollama is running (`curl http://localhost:11434/api/tags`)
- **Model not found:** Pull the model with `ollama pull qwen2.5-coder:32b`
- **Command not in PATH:** Use the full path `/home/fabiano/.opencode/bin/opencode` or run `source ~/.bashrc`

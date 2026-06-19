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

## Troubleshooting

- **Config not loading:** Ensure the file is at `~/.config/opencode/opencode.jsonc` (case-sensitive, JSONC format)
- **Ollama not responding:** Verify Ollama is running (`curl http://localhost:11434/api/tags`)
- **Model not found:** Pull the model with `ollama pull qwen2.5-coder:32b`
- **Command not in PATH:** Use the full path `/home/fabiano/.opencode/bin/opencode` or run `source ~/.bashrc`

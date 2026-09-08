# Review (Claude, direto — gateway sem ANTHROPIC_API_KEY configurada)

Diff: `a264ea7` (`agents/carwatch`, fix real de extract anchoring + case-folding).

## Achado real

**`_lowercase_drivetrain`/`_uppercase_range_cycle`/`_lowercase_status` (models.py) não fazem
`.strip()`, ao contrário do padrão já estabelecido no mesmo arquivo.**

`_normalize_type_synonyms` (já existente, linha ~78) faz `v.strip().lower()`. Os três
validators novos deste commit fazem só `v.lower()` / `v.upper()`:

```python
@field_validator("drivetrain", mode="before")
@classmethod
def _lowercase_drivetrain(cls, v):
    return v.lower() if isinstance(v, str) else v
```

O próprio commit existe porque o LLM devolveu um valor em casing inesperado
(`drivetrain="AWD"` contra um `Literal` minúsculo) — ou seja, a robustez do modelo aqui já é
conhecida como imperfeita. Se ele também devolver `"AWD "` (espaço à direita) ou `" awd"`,
`.lower()` sozinho não resolve e o `Literal["fwd","rwd","awd"]` rejeita, exatamente a mesma
classe de falha que este commit está tentando fechar. É inconsistência com o padrão já
estabelecido no arquivo, fácil de perder porque os três validators novos foram escritos por
cópia um do outro, não do validator mais antigo que já tinha a lição aprendida.

**Correção sugerida:** `v.strip().lower()` / `v.strip().upper()` nos três.

## Riscos, não confirmados como bug (faltam arquivos fora do diff)

- **Mistura de idioma no anchor:** o texto injetado em `extract_one_item` é em PT-BR
  (`"[Este item foi classificado como sendo especificamente sobre: ..."`), mas não vejo o
  `SYSTEM_PROMPT` de `extract.py` neste diff — se ele for em inglês, o anchor pode ter menos
  efeito do que se estivesse no mesmo idioma das instruções do sistema. Vale conferir.
- **Acoplamento posicional SQL↔tupla:** `item_id, url, title, summary, source_id,
  source_tier, classified = row` depende da ordem exata do `SELECT` correspondente — já era
  assim antes deste commit, mas cada nova coluna adicionada (como `classified` agora) aumenta
  a chance de um desalinhamento silencioso numa mudança futura no SELECT. Não é uma regressão
  deste commit, mas o commit é o lugar natural para trocar por algo nomeado (`namedtuple`,
  `Row` do psycopg) já que a tupla cresceu de 6 para 7 campos.

## O que está correto

- Ordem das colunas do novo `SELECT` bate exatamente com o unpacking da tupla.
- `if target_brand or target_model:` cobre o caso de `classified` sem essas chaves sem
  quebrar (fica sem anchor, comportamento anterior).
- `max_tokens` 1024→1536 é justificado corretamente no comentário (Anthropic cobra por token
  gerado, não pelo teto) — não é over-provisioning que custa dinheiro à toa.
- Teste novo (`test_run_extract_anchors_the_prompt_to_classifys_target_vehicle`) exercita o
  caminho real via mocks e afirma o conteúdo do anchor no texto enviado — cobertura direta do
  bug que motivou o commit.

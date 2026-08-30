# infra/systemd

Unidades **systemd de usuário** (`systemctl --user`) ligadas à infra do homelab
— não a um agente específico (esses trazem o próprio `systemd/`).

## comfyui-idle-stop

Desliga o container `comfyui` depois de ~1h ocioso. O ComfyUI é sob demanda:
sobe com `docker start comfyui` quando você vai gerar, e este timer o derruba
sozinho para não segurar ~20 GiB de RAM + VRAM à toa.

Instalar (rodar como o usuário, sem `sudo`, **a partir da raiz do repo**). O
`.service` assume que o repo está em `~/homelab-ai` (`ExecStart=%h/homelab-ai/...`);
se estiver em outro lugar, ajuste o `ExecStart`.

```bash
mkdir -p ~/.config/systemd/user
ln -sf "$PWD/infra/systemd/comfyui-idle-stop.service" ~/.config/systemd/user/
ln -sf "$PWD/infra/systemd/comfyui-idle-stop.timer"   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now comfyui-idle-stop.timer
systemctl --user list-timers comfyui-idle-stop.timer
```

Testar na mão: `infra/scripts/comfyui-idle-stop.sh` (não faz nada se o container
estiver parado, ocupado ou com atividade recente nos logs).

FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
COPY custom_nodes/ComfyUI-Manager/requirements.txt /tmp/manager-requirements.txt
COPY custom_nodes/ComfyUI-LTXVideo/requirements.txt /tmp/ltxvideo-requirements.txt
COPY custom_nodes/comfyui-ollama/requirements.txt /tmp/ollama-node-requirements.txt
RUN pip install --no-cache-dir \
    -r /tmp/requirements.txt \
    -r /tmp/manager-requirements.txt \
    -r /tmp/ltxvideo-requirements.txt \
    -r /tmp/ollama-node-requirements.txt

# Imagem base traz torch cu128. LTX 2/2.3 usa texto encoder Gemma3-12B nvfp4,
# cujo dequant otimizado (comfy-kitchen) exige torch com build CUDA 13.0+ nesta
# GPU Blackwell (sm_120) — sem isso ele cai num fallback "eager" que materializa
# os pesos inteiros e estoura os 16GB de VRAM (CUDA OOM confirmado nos logs).
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cu130 \
    torch==2.9.0+cu130 torchvision==0.24.0+cu130 torchaudio==2.9.0+cu130
# O pacote pip do NVRTC pra CUDA 13 mudou de layout (nvidia/cu13/lib/ em vez de
# nvidia/cuda_nvrtc/lib/) e o torch 2.9.0+cu130 não acha libnvrtc-builtins.so.13.0
# sozinho — falha silenciosa em log, mas fatal (derruba o processo) assim que um
# kernel precisa de JIT (ex.: abs() em tensor complexo, usado no RoPE do LTX).
ENV LD_LIBRARY_PATH=/opt/conda/lib/python3.11/site-packages/nvidia/cu13/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64

RUN mkdir -p /opt/comfyui-python \
    && printf '%s\n' \
        '"""Runtime compatibility patches for mounted ComfyUI custom nodes."""' \
        '' \
        'import torch.nn.functional as torch_functional' \
        '' \
        'try:' \
        '    import kornia.geometry.transform.pyramid as kornia_pyramid' \
        'except Exception:' \
        '    kornia_pyramid = None' \
        '' \
        'if kornia_pyramid is not None and not hasattr(kornia_pyramid, "pad"):' \
        '    kornia_pyramid.pad = torch_functional.pad' \
        > /opt/comfyui-python/sitecustomize.py
ENV PYTHONPATH=/opt/comfyui-python

WORKDIR /comfyui
EXPOSE 8188
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-cuda-malloc"]

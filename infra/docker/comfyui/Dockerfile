FROM pytorch/pytorch:2.13.0-cuda13.0-cudnn9-runtime@sha256:db80a41f8428644cebcb3d75b0b62df334ab6c0e75785951eb25f48bfbd42407

RUN apt-get update && apt-get install -y --no-install-recommends \
    git libgl1 libglib2.0-0 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# PyTorch 2.13 aplica PEP 668 no Python da imagem. O venv herda a stack
# Torch/CUDA oficial sem alterar o ambiente gerenciado pelo sistema.
RUN python -m venv --system-site-packages /opt/comfyui-venv \
    && /opt/comfyui-venv/bin/pip install --no-cache-dir pip==26.2.1
ENV PATH=/opt/comfyui-venv/bin:$PATH

COPY requirements.txt /tmp/requirements.txt
COPY custom_nodes/ComfyUI-Manager/requirements.txt /tmp/manager-requirements.txt
COPY custom_nodes/ComfyUI-LTXVideo/requirements.txt /tmp/ltxvideo-requirements.txt
COPY custom_nodes/comfyui-ollama/requirements.txt /tmp/ollama-node-requirements.txt
RUN pip install --no-cache-dir \
    'click>=8,<8.3' \
    -r /tmp/requirements.txt \
    -r /tmp/manager-requirements.txt \
    -r /tmp/ltxvideo-requirements.txt \
    -r /tmp/ollama-node-requirements.txt

# A base oficial já traz Torch e CUDA 13.0 alinhados. Isso evita instalar uma
# segunda stack Torch sobre uma imagem CUDA 12.8 e mantém suporte a Blackwell
# (sm_120), necessário pelo dequant otimizado do LTX/Gemma nvfp4.

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

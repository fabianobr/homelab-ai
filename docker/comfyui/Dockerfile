FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
COPY custom_nodes/ComfyUI-Manager/requirements.txt /tmp/manager-requirements.txt
COPY custom_nodes/ComfyUI-LTXVideo/requirements.txt /tmp/ltxvideo-requirements.txt
COPY custom_nodes/autodownloadmodels/requirements.txt /tmp/autodownloadmodels-requirements.txt
COPY custom_nodes/comfyui_model_installer/requirements.txt /tmp/model-installer-requirements.txt
COPY custom_nodes/hf-model-downloader/requirements.txt /tmp/hf-model-downloader-requirements.txt
RUN pip install --no-cache-dir \
    -r /tmp/requirements.txt \
    -r /tmp/manager-requirements.txt \
    -r /tmp/ltxvideo-requirements.txt \
    -r /tmp/autodownloadmodels-requirements.txt \
    -r /tmp/model-installer-requirements.txt \
    -r /tmp/hf-model-downloader-requirements.txt

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

FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
# ComfyUI-Manager extra deps
COPY custom_nodes/ComfyUI-Manager/requirements.txt /tmp/manager-requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/manager-requirements.txt

WORKDIR /comfyui
EXPOSE 8188
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"]

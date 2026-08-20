# ViralClip V4.2 — Lightning FREE CPU Worker

Este worker foi projetado **somente** para o primeiro Studio gratuito de 4 CPUs da Lightning. Ele não contém código para iniciar T4/GPU, não usa `lightning-sdk` para trocar de máquina e rejeita um ambiente que anuncie GPU.

## No Studio gratuito

1. Use o Studio que aparece como CPU/free CPU. **Não troque para GPU.**
2. Copie o projeto ViralClip V4.2 para o Studio.
3. Instale as dependências: `pip install -r requirements.txt`.
4. Defina um token forte: `export VIRALCLIP_LIGHTNING_TOKEN="<um-token-longo>"`.
5. Inicie: `python -m lightning_worker.run`.
6. Exponha a porta 8000 pelo mecanismo normal de porta/app do Lightning Studio e copie a URL HTTPS.

## No PC com ViralClip

No `.env`:

```env
LIGHTNING_ENABLED=1
LIGHTNING_CLOUD_URL=https://SUA-URL-DO-WORKER
LIGHTNING_CLOUD_TOKEN=O-MESMO-TOKEN
COMPUTE_MODE=auto
```

O ViralClip envia preferencialmente áudio FLAC mono 16 kHz e proxies curtos; o vídeo original permanece no PC. Uploads são fragmentados e resumíveis, usam SHA-256 e o worker mantém apenas 1 tarefa pesada simultânea.

## Garantia de custo

`LIGHTNING_FREE_CPU_ONLY` é fixado como `True` no aplicativo e no worker. Se o endpoint remoto indicar GPU/máquina incompatível, o ViralClip rejeita o worker e continua localmente.

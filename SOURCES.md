# Referências técnicas usadas no desenho

Este projeto foi reimplementado como uma base própria em Python. Ele não inclui cópias dos repositórios abaixo.

## 1. Anil-matcha/AI-Youtube-Shorts-Generator

Ideias aproveitadas no desenho:
- pipeline download → transcrição → análise de highlights → render;
- seleção de momentos por sinais de viralidade;
- suporte a vídeos longos e deduplicação de highlights;
- Whisper e geração 9:16;
- backend de LLM substituível.

Repositório:
https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator

## 2. junaidify/video_clipper

Selecionado como uma das referências mais completas encontradas na busca “Auto clip”.

Ideias aproveitadas no desenho:
- Smart Clip híbrido (NLP + LLM opcional);
- modo manual;
- modo sequencial;
- biblioteca/projetos;
- perfis/padrões de corte;
- legendas e texto no vídeo;
- thumbnails;
- interface web e deploy em container.

Repositório:
https://github.com/junaidify/video_clipper

## Implementação deste ZIP

A implementação deste ZIP foi criada do zero para integrar essas ideias em uma base única FastAPI + SQLite + faster-whisper + FFmpeg, com suporte opcional a servidor OpenAI-compatible/LM Studio.

## Aceleração AMD/Windows adicionada nesta versão
- Microsoft DirectML — backend DirectX 12 para AMD/Intel/NVIDIA.
- Microsoft DirectML / PyTorch audio / Whisper — implementação de referência usada pelo `setup_amd_gpu.bat`.
- FFmpeg AMF — o projeto detecta `h264_amf` e usa o encoder AMD quando disponível.

## YouTube 2026
- yt-dlp EJS setup guide: external JavaScript runtime + yt-dlp-ejs are required for full YouTube support.
- yt-dlp PO Token guide: current recommendation is a PO Token provider; missing PO tokens can lead to HTTP 403.
- yt-dlp-getpot-wpc: PO Token provider maintained by a yt-dlp core maintainer; this project uses it as the automatic 403 fallback.

## V2.1 — referências de reframing/face tracking

- OpenCV Zoo — YuNet face detector model (modelo baixado em tempo de instalação, não redistribuído no ZIP).
- fralapo/clippyme — referências públicas de pipeline de detecção/tracking/reframe pesquisadas para separar detecção, tracking e composição.
- obi19999/smart-video-reframe — referência pública pesquisada para reframing vertical.

A V2.1 implementa código próprio sobre OpenCV/FFmpeg e não copia arquivos binários/modelos para o pacote.


## V3.4 runtime provenance

- `faster-whisper` / CTranslate2: dependências Python conforme `requirements.txt`.
- `whisper.cpp`: runtime opcional instalado localmente pelo setup; o ZIP da release não inclui executáveis ou modelos de terceiros.
- FFmpeg/FFprobe: usados para normalização, benchmark, análise e render local.
- Resultados de benchmark e caches são artefatos locais em `data/` e não devem ser distribuídos na release.

## V4.1 — referências de produto estudadas

Os dumps HTML/estado de aplicações enviados pelo usuário em agosto de 2026 foram usados apenas para identificar padrões de produto e estruturas conceituais, como editor em massa, templates, Brand Kit, estados de projeto, tracks, layouts por speaker e sugestões de B-roll. O código da V4.1 foi implementado na base própria FastAPI/SQLite/FFmpeg do ViralClip; nenhuma dependência exige copiar bundles, assets privados ou endpoints proprietários dessas aplicações.

A implementação V4.1 também mantém as referências abertas já documentadas acima para FFmpeg, yt-dlp, Whisper e aceleração local.

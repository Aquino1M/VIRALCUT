# Arquitetura — ViralClip AI V2

## Princípio

A V2 continua local-first e deliberadamente simples de operar: FastAPI + Jinja + SQLite no painel, FFmpeg como motor de mídia, Whisper local e workers em `ThreadPoolExecutor` com concorrência pesada limitada a 1.

## Fluxo de projeto

1. `app/main.py` recebe URL ou upload.
2. `projects.normalize_project_settings()` normaliza prompt, duração, idioma, layout, legenda, fonte, faixa e overlays.
3. `jobs.py` normaliza a fonte localmente (`ingest.py`).
4. FFprobe coleta duração/resolução/codec e é criada a thumbnail da fonte.
5. `transcriber.py` executa Whisper e emite progresso.
6. `analyzer.py`/`llm.py` escolhe candidatos, ou o modo manual/sequencial cria ranges.
7. Cada clip recebe `clip_edits` e `caption_cues` independentes.
8. `render.py` compõe layout → captions ASS → overlays → encoder.
9. `h264_amf` é preferido e `libx264` é fallback.
10. Projeto e biblioteca são atualizados no SQLite.

## Editor

### Estado

`editor.py` mantém por clip:

- caption preset/config;
- layout preset/config;
- overlays;
- tracks e visibilidade.

O transcript original não é destruído. Correções do usuário vão para `caption_cues`.

### Preview

Há dois níveis:

- browser: HTML/CSS/JS, instantâneo;
- render preview: FFmpeg em 540x960, cacheado pelo hash do estado.

O render final é separado e permanece 1080x1920 nos projetos verticais.

### Captions

`captions.py` resolve presets e gera ASS/libass com cor ativa, posição, outline, fonte e timing. O preset Green Fresh é apenas um default editável.

### Fontes

`fonts.py` resolve:

1. `data/fonts/`;
2. fontes já instaladas no Windows;
3. fallback lógico.

As fontes abertas baixadas são servidas ao browser pelo próprio app para o preview visual usar a mesma família do render.

### Layouts

`layouts.py` é um registry de geometrias. Layouts multi-painel duplicam a fonte como fallback, garantindo render mesmo sem speaker/face metadata. A arquitetura aceita futura atribuição de speakers por painel.

### Brand Kit

`brand_assets` armazena logos/watermarks/imagens. O edit state guarda referências e geometria. `overlays.py` gera uma composição RGBA aplicada pelo FFmpeg.

## Render queue

`render_queue.py` mantém registros em `clip_renders`:

- queued;
- rendering;
- done;
- error;
- progress;
- encoder;
- resolução;
- tamanho;
- tempo de render;
- caminho do arquivo.

Previews são reutilizados quando o hash efetivo do estado não mudou.

## Banco

SQLite mantém compatibilidade e migrações idempotentes.

Tabelas principais:

- `users`
- `projects`
- `clips`
- `creator_profiles`
- `clip_edits`
- `caption_cues`
- `user_presets`
- `clip_renders`
- `project_assets`
- `brand_assets`

## Performance alvo

PC de referência: i5-4590 / 16 GB RAM / RX 580 8 GB.

- 1 projeto pesado por vez;
- 1 render final pesado por vez;
- Whisper CPU limitado a 3 threads quando DirectML não está ativo;
- preview reduzido;
- AMF preferencial;
- cache de previews;
- paginação da biblioteca.

## Crescimento futuro

Para produção multiusuário:

```text
FastAPI
  ↓
PostgreSQL
  ↓
Redis Queue
  ↓
CPU/GPU Workers
  ↓
S3/R2
```

O modelo `clip_edits` + tracks foi criado para permitir evolução sem transformar a V2 agora em um clone completo do Premiere/CapCut.


## V3.2 — Hybrid Worker

A fonte de verdade de processamento é o **Local Worker**. A interface local ou futura interface Vercel usa o **Worker Protocol v1** para criar e controlar jobs; WebGPU/WebGL/Canvas ficam restritos ao preview.

Fluxo pesado: `hardware auto -> ingest -> transcrição -> highlights -> tracking por janela -> Auto Edit -> render`. O tracking nunca precisa percorrer o vídeo inteiro antes de saber quais trechos serão usados. Jobs, etapas, heartbeat e controles ficam persistidos em SQLite.

Hardware Auto 2.0 testa o encoder em vez de confiar apenas na presença do nome no FFmpeg: NVIDIA/NVENC, AMD/AMF, Intel/QSV e CPU/libx264 possuem fallback automático.


## V3.4 — Performance Engine

O Local Worker continua sendo o único executor de processamento pesado. A seleção ASR agora é feita por um registro de backends com benchmark persistido no Hardware Profile 3.0. A ordem de candidatos depende da GPU, mas disponibilidade por pacote/driver não equivale a seleção.

Pipeline de transcrição:

1. identificar origem e consultar cache;
2. Pass A: transcrever segmentos sem timestamps por palavra;
3. escolher os melhores cortes;
4. Pass B: refinar somente as janelas selecionadas com timestamps por palavra;
5. executar Face Tracking somente nos cortes necessários;
6. manter render final preso ao snapshot/original.

Cache em `data/cache/asr/` é limitado por LRU e nunca deve apagar uploads, projetos ou renders do usuário. Runtimes opcionais vivem em `data/runtime/` e não fazem parte do ZIP de release.

## V4.1 — Smart Studio Engine

A V4.1 mantém o princípio local-first e transforma os recursos isolados do Studio em um fluxo único. O projeto passa a ter um **Command Center** que coordena Studio Templates, Brand Kits, Auto Director, B-roll, render final, publicação local e analytics sem misturar essas responsabilidades no mesmo serviço.

### Componentes novos

- `viral_score.py`: ViralScore 2.0 explicável em oito dimensões, persistido em `clips.analysis_json`.
- `studio_templates.py`: templates combinados de layout/legenda/Auto Edit aplicáveis em lote.
- `brand_kits.py`: kits nomeados e editáveis com fonte, cores, CTA e assets.
- `performance.py`: política Auto/Básico/Balanceado/Performance para proxy, preload e densidade de cards; não altera o render final.
- `publishing.py`: fila local de publicação com status e checagem real de existência do MP4 exportado.
- `waveform.py`: waveform cacheado em JSON para a timeline.
- `auto_edit.py`: Smart Director por cena com decisões de layout/speaker gravadas como itens editáveis.
- `render_queue.py`: cache de render final por `settings_hash + editor_revision`.

### Fluxo V4.1

```text
Fonte original
  ↓
Transcrição Pass A
  ↓
Highlights + ViralScore 2.0
  ↓
Refino Pass B + speaker/face windows
  ↓
Smart Director + Timeline Pro
  ↓
Studio Template + Brand Kit + B-roll
  ↓
Proxy adaptativo no editor
  ↓
Render final no original + cache por revisão
  ↓
Fila local de publicação
  ↓
Viralytics
```

### PWA e mobile

O manifest e o service worker armazenam somente o shell estático. Vídeos, renders, uploads e endpoints de mídia do usuário não entram no cache offline. O processamento pesado continua no Local Worker.

### Regra de qualidade

Os modos de desempenho podem reduzir **somente** proxy/preload/densidade visual. A resolução e a mídia de entrada do render final continuam sendo determinadas pelo projeto e pelo arquivo original.

## V4.2 — Adaptive Compute Fabric

A fonte da verdade permanece SQLite/local. Cloud é compute efêmero e nunca armazena o projeto principal.

```text
Projeto/Timeline local
       ↓
ProcessingTask
       ↓
Adaptive Scheduler (ETA + carga + histórico)
       ├── local_cpu
       ├── local_gpu
       └── cloud_cpu → Lightning primeira CPU gratuita
                         (1 heavy slot)
```

### Regras de segurança/custo

`cloud_gpu` é proibido nesta distribuição. Tanto cliente quanto worker validam `free_cpu_only`. Não existe control plane que inicie T4/GPU. Se a nuvem falhar, a tarefa é refeita pelo backend local comprovado.

### Transporte

Vídeo completo não é enviado por padrão. ASR usa FLAC mono 16 kHz; tracking usa proxy de janela. Uploads são divididos em chunks com SHA-256 e podem ser retomados/deduplicados. O worker valida a mídia montada com FFprobe.

### Resiliência

Jobs Cloud usam SQLite, idempotency keys, cache por conteúdo, heartbeat, lease e recuperação pós-restart. O cliente possui circuit breaker. Eventos SSE existem no worker; polling permanece fallback.

### Inteligência

ViralScore 3.0, Creator Intelligence, busca semântica, transcript Q&A, Prompt-to-Edit, revisões e Quality Guard ficam separados do pipeline de mídia para poderem evoluir sem comprometer render/fallback.

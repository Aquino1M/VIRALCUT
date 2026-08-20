# ViralClip Studio V3 — Design

**Data:** 2026-08-16  
**Base:** ViralClip AI V2.2  
**Objetivo:** transformar o ViralClip em um editor de vídeo local-first completo, acelerado pelo hardware do usuário e preparado para ser incorporado futuramente como uma feature do SaaS hospedado na Vercel.

## 1. Visão do produto

A V3 deixa de ser apenas um gerador de cortes e passa a ser um **Local AI Video Studio**. O usuário continua podendo criar cortes automáticos em poucos cliques, mas também recebe um editor multicamada, edição por transcrição, automações de IA, presets, render em lote e um worker local que usa NVIDIA, AMD, Intel ou CPU.

O mesmo motor será utilizado em dois modos:

1. **Standalone local:** iniciado por `VIRALCLIP.bat`, com interface no navegador e processamento integral no PC do usuário.
2. **SaaS + Local Worker:** futuramente o site do usuário na Vercel cria e controla jobs, enquanto o worker instalado no PC executa download, transcrição, tracking, edição automática e render.

O vídeo não precisa ser enviado ao servidor para ser processado. No modo SaaS, o worker local faz conexões de saída HTTPS para buscar jobs e publicar estado/resultados, evitando expor uma porta pública no computador do usuário.

## 2. Princípios

- Local-first e privacy-first.
- Funcionar sem GPU dedicada.
- Detectar hardware automaticamente; não exigir que o usuário saiba escolher CUDA/AMF/QSV/DirectML.
- Aproveitar o máximo de aceleração disponível sem tornar um backend obrigatório.
- Não quebrar os fluxos estáveis da V2.2.
- Preview rápido e render final fiel ao mesmo estado de timeline.
- Um único formato de projeto, independente do frontend.
- API versionada desde o início para permitir futura integração com Vercel/Codex.
- Recursos online são opcionais, nunca necessários para abrir/editar/renderizar um projeto local.
- Não copiar código proprietário nem depender de assets proprietários das referências utilizadas.

## 3. Decomposição da V3

O escopo é grande demais para uma alteração monolítica segura. A V3 será implementada em quatro entregas internas, mas distribuída ao usuário como um único produto:

### V3.0 — Runtime, Hardware e Local Worker

- `VIRALCLIP.bat` único.
- Hardware Manager.
- Backend Router.
- API `/api/v1`.
- Job engine persistente.
- Cache/proxy/render pipeline.
- preparação para SaaS/Vercel.

### V3.1 — Editor Pro

- React/TypeScript/Vite como frontend do editor, compilado para arquivos estáticos servidos pelo FastAPI.
- Timeline multicamada.
- Canvas editável.
- Editor por transcrição.
- Waveform, markers, snapping, atalhos, undo/redo e autosave.
- Render compiler baseado na timeline.

### V3.2 — Auto Edit + IA

- Smart cuts.
- filler/silence/repetition removal.
- smart zooms.
- reframing por speaker/face.
- B-roll suggestions.
- títulos, hooks, CTA, emojis/memes/SFX opcionais.
- score e explicação.
- tradução/caption assist opcional.

### V3.3 — Bridge para SaaS/Vercel

- Device pairing.
- worker outbound job polling.
- capabilities do dispositivo.
- job claims/idempotência.
- upload/download opcional de resultados.
- contrato de API/documentação para o frontend futuro.

Cada estágio precisa permanecer executável e testável antes de seguir para o próximo.

## 4. Abordagens consideradas

### A. Evoluir Jinja + JavaScript atual

**Vantagem:** menor mudança inicial.  
**Problema:** timeline multicamada, virtualização, keyframes, seleção e canvas ficarão difíceis de manter em JavaScript inline. O futuro frontend na Vercel exigiria reescrita significativa.

### B. React/TypeScript para o editor + FastAPI/FFmpeg como motor — RECOMENDADO

O backend permanece Python, o render continua FFmpeg/ASS e o editor vira uma SPA React/Vite. A build do frontend é empacotada no ZIP, então o usuário final não precisa instalar Node para usar o ViralClip. No futuro, componentes e protocolo do editor podem ser reaproveitados no SaaS.

### C. Electron/Tauri/Remotion como aplicação completa

Permitiria uma experiência desktop mais integrada, mas aumentaria drasticamente o runtime, distribuição e superfície de bugs. Também reduziria o reaproveitamento direto do backend atual.

**Decisão:** abordagem B.

## 5. Estrutura de código alvo

```text
viralclip/
  app/
    api/v1/
    core/
    services/
    static/editor/
    templates/

  engine/
    hardware/
    ingest/
    audio/
    transcription/
    scenes/
    speakers/
    tracking/
    clipping/
    timeline/
    layouts/
    captions/
    effects/
    broll/
    render/
    export/
    jobs/
    cache/

  worker/
    client.py
    pairing.py
    protocol.py

  frontend/
    src/
      editor/
      timeline/
      canvas/
      transcript/
      panels/
      stores/
      api/

  tools/
  tests/
  VIRALCLIP.bat
```

A migração será incremental: arquivos existentes continuam funcionando enquanto os módulos são extraídos para `engine/`.

## 6. Formato único de projeto

O estado editável deixa de ficar espalhado entre campos de clip e passa a ter uma composição serializável.

```json
{
  "schemaVersion": 3,
  "composition": {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "duration": 51.2
  },
  "tracks": [],
  "assets": {},
  "markers": [],
  "settings": {},
  "metadata": {}
}
```

### Track

```json
{
  "id": "video-main",
  "type": "video",
  "name": "Vídeo principal",
  "hidden": false,
  "locked": false,
  "muted": false,
  "items": []
}
```

### Tipos de item

- video
- audio
- captions
- text
- image
- svg
- shape
- logo/watermark
- broll
- music
- sfx
- adjustment/effect
- layout/background
- freeze-frame

### Propriedades comuns

- `from`
- `duration`
- `sourceStart`
- `playbackRate`
- `opacity`
- `x/y`
- `width/height`
- `rotation`
- `crop`
- `volumeDb`
- `fadeIn/fadeOut`
- `zIndex`
- `keyframes`

Esse modelo foi escolhido porque separa conteúdo, geometria e tempo e corresponde ao comportamento de um editor não destrutivo.

## 7. Editor Pro

### Layout visual

- barra superior: nome, autosave, undo/redo, Auto Edit, preview, export;
- painel esquerdo: Texto/Transcrição e Propriedades;
- canvas central;
- painel direito: Templates, Texto, Formas, Brand Kit, Biblioteca, Música, IA, Emoji, Memes, Fotos/Filtros;
- timeline inferior multicamada.

### Timeline

Recursos obrigatórios:

- zoom horizontal;
- ruler/timecode;
- playhead arrastável;
- waveform;
- thumbnails de vídeo;
- tracks reordenáveis;
- hide/lock/mute;
- selection box;
- multi-select;
- drag/drop;
- trim esquerda/direita;
- split;
- duplicate;
- delete;
- ripple delete;
- magnetic snapping;
- markers;
- copiar/colar;
- undo/redo;
- autosave incremental.

### Atalhos

- Espaço: play/pause
- S: split
- Delete/Backspace: remover
- Ctrl+Z / Ctrl+Y: undo/redo
- Ctrl+C / Ctrl+V: copiar/colar
- setas: navegar frames
- Shift+setas: salto maior
- M: mute selecionado
- L: lock
- +/-: zoom timeline

Atalhos devem ser configuráveis posteriormente, mas a V3 começa com esse mapa.

## 8. Canvas e transformações

Cada item visual pode ser selecionado diretamente no canvas.

- mover;
- resize por handles;
- rotação;
- crop;
- zoom;
- opacidade;
- borda/raio;
- alinhamento;
- safe zones;
- guides;
- snap para centro/bordas;
- contexto 9:16, 4:5, 1:1 e 16:9;
- drag de legendas e overlays;
- preview de face tracking/layout.

A renderização do canvas no navegador é apenas uma visualização do mesmo JSON que será compilado para FFmpeg/ASS.

## 9. Edição por transcrição

O transcript editor é uma feature central.

- palavra e parágrafo;
- word-level timestamps;
- clicar na palavra move o playhead;
- seleção de frase destaca o intervalo na timeline;
- edição textual corrige legenda;
- apagar palavra/frase pode remover o respectivo intervalo do vídeo;
- opção global `Cortar vídeo ao remover palavras`;
- busca/substituição;
- remover filler words;
- remover repetições imediatas;
- remover silêncios acima de limiar;
- preservar respiração mínima configurável;
- detectar cenas e speakers;
- confidence visual para palavras duvidosas;
- restaurar trecho excluído sem perder o original.

Os cortes de texto são não destrutivos: viram operações/segmentos na timeline, não reescrita imediata do arquivo-fonte.

## 10. Hardware Manager universal

Ao iniciar, o ViralClip cria `data/system_profile.json`.

### Detectar

- CPU/modelo/threads;
- RAM disponível;
- GPU(s), fabricante e VRAM quando possível;
- FFmpeg;
- encoders disponíveis;
- NVENC;
- AMF;
- QSV;
- Vulkan;
- DirectML quando instalado;
- CUDA runtime;
- espaço em disco;
- modelos instalados.

### Render backend

Prioridade dinâmica:

**NVIDIA:** NVENC → libx264 fallback.  
**AMD:** AMF → libx264 fallback.  
**Intel:** QSV → libx264 fallback.  
**CPU:** libx264.

A disponibilidade real é confirmada executando probes do FFmpeg, não somente pelo nome da GPU.

### Transcription backend

- NVIDIA compatível: faster-whisper CUDA como primeira escolha;
- NVIDIA fallback: whisper.cpp CUDA/Vulkan/CPU;
- AMD Windows: whisper.cpp Vulkan como preferência; DirectML opcional quando saudável;
- Intel: whisper.cpp Vulkan/OpenVINO quando disponível; CPU fallback;
- CPU: whisper.cpp quantizado/int8 ou faster-whisper CPU como fallback de compatibilidade.

O projeto deve permitir trocar de backend em Configurações Avançadas, mas o modo automático é o padrão.

### Perfis

**ECO:** baixo consumo, preview reduzido, 1 job pesado.  
**BALANCEADO:** padrão automático.  
**TURBO:** maior batch/concorrência conforme VRAM/RAM.

## 11. VIRALCLIP.bat único

O arquivo raiz `VIRALCLIP.bat` é o entrypoint oficial.

### Primeira execução

1. localizar PowerShell;
2. verificar Windows suportado;
3. instalar/usar `uv` localmente;
4. obter Python compatível;
5. criar `.venv`;
6. instalar dependências base;
7. detectar GPU;
8. instalar extras adequados ao backend;
9. localizar/instalar FFmpeg quando necessário;
10. instalar/baixar modelos opcionais permitidos;
11. preparar fontes abertas;
12. rodar diagnóstico;
13. salvar system profile;
14. iniciar FastAPI/Local Worker;
15. abrir navegador.

### Execuções seguintes

Fast health check e start em poucos segundos, sem reinstalar tudo.

### Argumentos

```text
VIRALCLIP.bat
VIRALCLIP.bat --diagnose
VIRALCLIP.bat --repair
VIRALCLIP.bat --update
VIRALCLIP.bat --safe
VIRALCLIP.bat --no-browser
```

O BAT delegará a lógica complexa para scripts PowerShell/Python versionados para continuar legível/testável.

## 12. Local Worker e API v1

O FastAPI atual evolui para uma API estável.

### Capabilities

`GET /api/v1/capabilities`

Retorna:

- version;
- device ID;
- CPU/GPU;
- backends ativos;
- encoders;
- modelos;
- limites sugeridos;
- recursos suportados.

### Jobs

- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{id}`
- `POST /api/v1/jobs/{id}/cancel`
- `POST /api/v1/jobs/{id}/retry`
- `GET /api/v1/jobs/{id}/events`

Estados:

`queued → preparing → running → finalizing → done|failed|cancelled`

Jobs são persistidos em SQLite antes de entrar na fila. Reiniciar o PC não perde o trabalho.

### Segurança local

- bind padrão `127.0.0.1`;
- token local aleatório;
- CORS allowlist;
- nenhuma execução de shell arbitrário recebida da API;
- caminhos normalizados e confinados às pastas permitidas;
- uploads validados por tipo/tamanho;
- logs sem tokens/cookies.

## 13. Bridge futuro para Vercel

O site não tentará acessar diretamente uma porta pública no computador.

### Fluxo

1. usuário instala ViralClip Worker;
2. no SaaS, clica `Conectar este computador`;
3. SaaS gera código temporário;
4. worker troca código por `device_token`;
5. worker mantém heartbeat outbound;
6. SaaS grava job;
7. worker faz polling/long-poll HTTPS e reivindica o job;
8. worker processa localmente;
9. worker publica progresso/metadados;
10. resultado permanece local ou é enviado quando o usuário solicitar.

A camada de transporte será abstraída para permitir WebSocket/SSE futuramente, sem modificar o engine.

## 14. Transcrição, VAD e speakers

Pipeline:

```text
extract audio
→ VAD
→ ASR
→ word alignment
→ speaker segmentation opcional
→ sentence segmentation
→ transcript document
```

- timestamps por palavra;
- VAD para reduzir silêncio/hallucinação;
- diarização opcional quando backend/recursos permitirem;
- IDs de speaker reutilizados pelos layouts;
- cache do transcript por hash da fonte + backend + modelo.

WhisperX/pyannote podem ser disponibilizados como backend avançado opcional, especialmente em NVIDIA, mas a V3 não dependerá deles para funcionar.

## 15. Scene Detection e Face/Speaker Tracking

- PySceneDetect ou detector equivalente para boundaries;
- faces analisadas por cena;
- track IDs persistentes;
- smoothing;
- active-speaker heuristic;
- speaker diarization pode reforçar a decisão;
- crop interpolation;
- fallback central seguro;
- cache por hash.

Markers automáticos:

- mudança de cena;
- troca de speaker;
- silêncio;
- hook;
- punchline;
- provável B-roll;
- zoom sugerido.

## 16. Layout Engine 3.0

Layouts existentes continuam e passam a ser **scene-aware** e **timeline-aware**.

- Auto Inteligente
- Single
- Center
- Split
- Split Vertical
- Tri-Split
- Tri-Split Top
- Quad
- Six-Split
- React
- Brainrot
- Talking Head + B-roll
- Top/Bottom Podcast
- Podcast Dinâmico
- Choquei + Movimento
- Header/Notícias
- Story/Documentário

Cada cena pode trocar de crop/layout independentemente sem quebrar a legenda ou áudio.

Auto Layout escolhe composição com base em:

- número de rostos;
- posição relativa;
- speaker ativo;
- tipo de cena;
- B-roll disponível;
- preset do projeto.

## 17. Caption Engine 3.0

Legenda vira track/item de primeira classe.

- edição por palavra;
- seleção no canvas;
- keyframes simples de posição/escala;
- presets;
- speaker colors;
- palavra ativa;
- karaoke;
- pop/scaling/bounce;
- rainbow;
- background box;
- shadow/stroke;
- emojis opcionais;
- max lines/words/page;
- safe area;
- auto line breaking;
- preview idêntico ao render dentro das limitações do navegador;
- ASS como backend principal para burn-in.

## 18. Audio Engine

- waveform;
- loudness meter;
- EBU-like loudness normalization via FFmpeg;
- compressor;
- limiter;
- high-pass/low-pass básicos;
- denoise leve quando disponível;
- volume por item;
- fade;
- ducking automático de música sob fala;
- music track;
- SFX track;
- silence detection;
- auto remove/shorten silence;
- export de áudio separado.

## 19. B-roll, mídia e biblioteca

### Biblioteca local

- vídeos;
- imagens;
- SVGs;
- logos;
- músicas;
- SFX;
- memes;
- overlays;
- favorites;
- tags;
- busca.

### B-roll inteligente

A IA gera sugestões textuais e procura primeiro na biblioteca local. APIs externas de stock podem ser adicionadas posteriormente como providers opcionais.

O sistema não fará download automático de mídia potencialmente protegida sem uma fonte/provedor permitido.

## 20. Auto Edit

Auto Edit produz um **plano editável**, nunca uma caixa-preta irreversível.

### Etapas

1. analisar transcript;
2. detectar cenas/speakers;
3. identificar hook;
4. remover/encurtar silêncios;
5. sugerir filler removal;
6. escolher reframing/layout por cena;
7. inserir smart zooms;
8. sugerir B-roll;
9. inserir title cards quando preset permitir;
10. inserir SFX/emojis/memes quando preset permitir;
11. aplicar caption preset;
12. aplicar Brand Kit;
13. produzir score/explicação;
14. mostrar diff do que será alterado.

### Intensidades

- Clean: apenas limpeza e reframing;
- Viral: zooms, captions, hook, B-roll moderado;
- Max: edição agressiva, memes/SFX/emojis permitidos.

O usuário pode desmarcar operações antes de aplicar.

## 21. Smart Clip e score

O score deixa de ser um único valor opaco.

```text
Hook           9.2
Clareza        8.7
Emoção         7.9
Polêmica       8.4
Standalone     9.1
Retenção       8.8
Score final    8.8
```

A seleção de cortes combina:

- transcript;
- sentence boundaries;
- pausas;
- keywords;
- emoção textual;
- pergunta/resposta;
- mudança de assunto;
- heurísticas de duração;
- LLM opcional.

O usuário pode escolher objetivos: Podcast, Exposed/Polêmica, Educacional, Humor, Storytelling, Notícias, Vendas, Motivacional etc.

## 22. Templates e Brand Kit

Template completo pode incluir:

- aspect ratio;
- layout rules;
- caption preset;
- fonts;
- title style;
- colors;
- logo;
- watermark;
- CTA;
- music/SFX defaults;
- Auto Edit intensity;
- export defaults.

Presets podem ser salvos, duplicados, favoritados e aplicados em massa.

## 23. Proxy, cache e performance

- proxy 540p/720p;
- thumbnails strip em background;
- waveform cache;
- transcript cache;
- face/scene cache;
- render hash;
- partial preview 2–8 s;
- render somente do intervalo alterado quando possível;
- cache invalidation por dependência;
- preview em baixa resolução, final em nativo;
- controle de concorrência por perfil de hardware;
- cancelamento cooperativo de jobs;
- limpeza de cache por LRU/limite configurável.

## 24. Export

- MP4 H.264 padrão;
- HEVC opcional quando compatível;
- AV1 opcional quando hardware/FFmpeg suportarem;
- 9:16, 4:5, 1:1, 16:9;
- múltiplas saídas em lote;
- bitrate/quality presets;
- sem legenda / com legenda;
- SRT/VTT/ASS;
- transcript TXT/JSON;
- audio WAV/MP3;
- thumbnails;
- ZIP do projeto/cortes.

## 25. UX de projeto

Tela de criação passa a ter um wizard curto:

1. origem;
2. objetivo do conteúdo;
3. duração alvo;
4. layout;
5. caption/template;
6. Auto Edit intensity;
7. perfil de processamento Auto/Eco/Balanceado/Turbo.

O usuário pode clicar em `Rápido` e usar defaults automáticos sem atravessar todas as opções.

## 26. Recuperação e confiabilidade

- SQLite WAL;
- migrations versionadas;
- autosave transacional;
- job checkpoints;
- recovery no startup;
- arquivo-fonte nunca é alterado;
- atomic write para project state;
- render temporário → rename ao concluir;
- logs rotativos;
- botão Copiar diagnóstico;
- crash report local opcional;
- `--safe` desativa backends GPU/plugins avançados.

## 27. Testes

### Unitários

- hardware routing;
- timeline operations;
- transcript ripple edits;
- project schema migrations;
- caption compilation;
- layout decisions;
- job state machine;
- cache hashes;
- API contracts.

### Integração

- FastAPI TestClient;
- SQLite recovery;
- FFmpeg synthetic renders;
- 4 aspect ratios;
- multiple tracks;
- trim/split/ripple;
- captions + overlays + audio;
- hardware encoder fallback.

### Smoke real

Usar os vídeos de referência fornecidos para validar:

- podcast multi-person;
- Choquei + Movimento;
- notícias/header;
- documentário/story;
- face tracking;
- transcript edit;
- timeline render.

### Packaging

O ZIP final é extraído em pasta nova e a suíte de smoke/package tests roda contra o conteúdo extraído.

## 28. Licenças e dependências

- Preferir MIT/BSD/Apache e componentes redistribuíveis.
- Dependências GPL/AGPL ou com termos comerciais precisam ser avaliadas antes de serem incorporadas ao produto distribuído.
- Ferramentas usadas apenas externamente podem ser integradas via processo quando a licença permitir, mas isso deve ser documentado.
- Fontes proprietárias não serão redistribuídas.
- Assets/memes/músicas não serão empacotados sem licença apropriada.

## 29. Compatibilidade e migração

- Projetos V2.2 continuam abrindo.
- Na primeira edição V3, seu estado é migrado para `schemaVersion: 3`.
- A origem V2.2 é preservada para rollback/export.
- Endpoints V2 permanecem durante a transição interna; `/api/v1` vira a API pública estável da V3.

## 30. Critérios de aceitação da V3

A V3 só é considerada pronta quando:

1. `VIRALCLIP.bat` instala/inicia em PC limpo suportado e reiniciar é rápido;
2. NVIDIA, AMD, Intel e CPU possuem roteamento/fallback documentado e testado por probes/simulações;
3. um projeto V2.2 migra sem perder cortes;
4. timeline permite video/audio/caption/text/image e operações essenciais;
5. apagar palavras com ripple habilitado realmente altera o vídeo final;
6. canvas e render final usam o mesmo project state;
7. Auto Edit produz operações revisáveis;
8. tracking/layout funciona por cena;
9. jobs sobrevivem reinicialização;
10. API v1 reporta capabilities e jobs;
11. worker tem protocolo de pairing/job pronto para futura Vercel;
12. smoke renders reais passam nos vídeos de referência;
13. pacote não inclui credenciais, caches, banco de teste ou fontes proprietárias.

## 31. Escopo que fica preparado, mas não precisa de serviço externo na V3 local

- publicação direta TikTok/YouTube/Instagram;
- stock media providers pagos;
- colaboração multiusuário em tempo real;
- render cloud;
- billing/subscriptions;
- storage cloud.

A API e o formato de projeto devem permitir adicionar esses recursos no SaaS futuramente sem reescrever o engine local.

## 32. Referências funcionais utilizadas

As referências fornecidas pelo usuário mostram um editor com composição 1080×1920/29.97 fps, tracks independentes com estados hidden/locked/muted, itens de vídeo com crop e `faceTrackSceneId`, layout suggestions por cena e caption items com geometria/estilo. A V3 utiliza esses conceitos como referência funcional, mas mantém implementação, componentes, nomes internos e código próprios.

Pesquisa externa usada para decisões arquiteturais inclui projetos/tecnologias de edição automática, transcription/alignment, scene detection e aceleração local. Cada dependência real deverá passar pela revisão de licença antes de ser adicionada ao pacote.


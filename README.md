# ViralClip Studio V4.2 — Adaptive Smart Studio

Editor local-first em **Python + FastAPI + SQLite + FFmpeg** para transformar vídeos longos em cortes, encontrar highlights com IA e montar Shorts/Reels/TikToks com layout, face tracking, legendas, B-roll, música, SFX, filtros e efeitos.

A V3.3 mantém o Hybrid Worker da V3.2 e transforma o editor em um runtime leve: proxy 480p, layouts instantâneos no navegador, Save Snapshot revisionado, render preso à revisão salva, CTA removível e Timeline Pro realmente interativa. O render final continua usando a mídia original em qualidade nativa.


## Adaptive Smart Studio V4.2 · CPU grátis Lightning

A V4.2 mantém o V4.1 local-first e adiciona uma **Adaptive Compute Fabric** que trata CPU local, GPU local e a primeira CPU gratuita da Lightning como recursos independentes do mesmo pipeline. A nuvem é aceleração opcional: se estiver desligada, dormindo, sem internet, sem token ou rejeitada, o projeto continua localmente.

**Regra de custo desta build:** `LIGHTNING_FREE_CPU_ONLY=True` é fixa no código. O cliente rejeita workers que anunciem GPU/máquina paga; o worker remoto recusa executar em GPU; não existe código para iniciar T4, trocar hardware pelo Lightning SDK ou consumir créditos. Render remoto também fica bloqueado.

Principais adições V4.2:

- scheduler por **ETA real** com carga atual da máquina e histórico de velocidade;
- `local_cpu`, `local_gpu` e `cloud_cpu` como nós separados;
- Lightning Worker FastAPI/SQLite com 1 slot pesado, cache, idempotência, heartbeat/lease, recuperação após reinício e SSE;
- uploads resumíveis em chunks com SHA-256, deduplicação e validação por FFprobe;
- envio preferencial de áudio FLAC mono 16 kHz e proxies pequenos para tracking remoto;
- ASR Pass A/Pass B, highlights e tracking roteáveis para a CPU grátis com fallback local;
- Compute Dashboard e histórico de decisões do scheduler;
- ViralScore 3.0 explicável + Creator Intelligence calibrado somente com métricas reais;
- busca semântica e perguntas ancoradas no transcript;
- Prompt-to-Edit não destrutivo + checkpoints/restauração;
- Quality Guard 2.0, Thumbnail Brain, detecção de silêncio/cenas e loudness opcional;
- Auto Edit 2.0 com progress bar e Ken Burns;
- Templates/Brand Kits importáveis/exportáveis e overrides por plataforma.

Configuração da CPU gratuita: veja `LIGHTNING_FREE_CPU_SETUP.md`. Detalhes completos: `docs/V4.2_RELEASE_NOTES.md`. Relatório da implementação: `V4.2_IMPLEMENTATION_REPORT.md`.

## Smart Studio Engine V4.1

A V4.1 consolida o fluxo completo **capturar → criar → editar → renderizar → publicar → analisar** sem transformar o computador do usuário em uma render farm. O preview trabalha com proxies adaptativos, enquanto o MP4 final continua usando a mídia original.

Principais recursos desta release:

- **Command Center por projeto** com filtros de Pronto, Renderizando, Renderizado, Agendado, Publicado e Erro.
- **ViralScore 2.0** com hook, curiosidade, emoção, controvérsia, clareza, compartilhamento, comentários e retenção estimada.
- **Smart Director / Auto Director** por cena, com speaker-aware layout e Face Tracking apenas quando necessário.
- **Editor em Massa** para aplicar Studio Template, Brand Kit, Auto Director, B-roll e preparar MP4 em lote.
- **Studio Templates** e **Brand Kits nomeados/editáveis** aplicáveis a um ou muitos cortes.
- **Caption Engine 3.0** com presets After Effects 01/02/03, destaque por palavra e emojis opcionais.
- **Render Cache** por revisão/hash para não refazer um MP4 final que já está válido.
- **Waveform Cache** em JSON leve para a timeline carregar sem reanalisar o áudio a cada abertura.
- **Modos Básico, Balanceado e Performance**: mudam proxy e densidade da interface, nunca a qualidade do render final.
- **Fila de Publicação local** com checagem de exportação pronta; não publica em redes sociais sem conectores oficiais.
- **Viralytics** local e shell **PWA** para navegação/monitoramento mais leve no mobile.

No Windows, use **somente `VIRALCLIP.bat`** como entrada normal. O bootstrap detecta Python compatível e evita os comandos quebrados que apareciam no launcher antigo.

Veja `docs/V4.1_RELEASE_NOTES.md` para detalhes.

## ViralClip Studio V3 — histórico de compatibilidade

As seções abaixo preservam a documentação das versões V3.x para migração e diagnóstico de instalações antigas.

## Performance Engine V3.4

A V3.4 mantém o editor e o Hybrid Local Worker da V3.3 e troca a seleção de transcrição por um sistema **benchmark-driven**. O Worker testa backends compatíveis, persiste o vencedor e evita repetir rotas que falharam na mesma configuração.

- **NVIDIA:** CUDA benchmarkado → whisper.cpp Vulkan → CPU.
- **AMD/Intel no Windows:** whisper.cpp Vulkan benchmarkado → DirectML aprovado → CPU.
- **Transcrição em duas passagens:** segmentos no vídeo completo e timestamps por palavra apenas nos cortes escolhidos.
- **Cache ASR:** áudio normalizado, segmentos e janelas refinadas são reutilizados quando a origem/configuração é idêntica.
- **Sem perda de qualidade:** proxy e otimizações são exclusivos da edição/análise; o render final continua usando a mídia original e as configurações finais do projeto.
- **Hardware Auto 3.0:** exibe backend ASR selecionado, x realtime, último benchmark e fallback.

Veja `docs/V3.4_RELEASE_NOTES.md` para os detalhes desta versão.

## Início rápido: um único BAT

No Windows, a entrada normal agora é somente:

```bat
VIRALCLIP.bat
```

Na primeira execução ele cria o ambiente Python, instala dependências, verifica FFmpeg, configura aceleração, baixa modelos/fontes abertas quando necessário, prepara a **Biblioteca Leve (até ~2 GB)** e abre o navegador. Nas execuções seguintes reutiliza os arquivos locais.

Modos opcionais do mesmo BAT:

```bat
VIRALCLIP.bat start
VIRALCLIP.bat diagnose
VIRALCLIP.bat repair
VIRALCLIP.bat update
VIRALCLIP.bat safe
```

`safe` força CPU/libx264 para recuperar uma instalação com driver problemático.

Compatibilidade: V3.1 e V3.2 continuam suportadas na migração de projetos.

## Studio Shell V3.2

A interface principal foi reorganizada para seguir o fluxo de trabalho do editor, sem copiar código proprietário de terceiros. A criação começa pela fonte: **Cole o link do vídeo** ou arraste um arquivo local; depois o usuário abre as configurações avançadas, escolhe layout, legenda e Auto Edit antes do processamento.

- **Navegação mobile** com barra inferior e botão central de criação.
- Sidebar desktop por etapas: Criar, Capturar e Sistema.
- **Hardware Local** mostra GPU/backend/encoder e perfil detectado.
- **Biblioteca Inteligente** pesquisa B-roll, SFX, músicas, filtros, efeitos, transições e mídia própria.
- **Templates** reúne layouts, estilos de legenda e estilos do Director AI.
- **Brand Kit** centraliza logos, watermarks, imagens e overlays reutilizáveis.
- Meus Vídeos reúne os cortes já gerados com acesso a assistir, editar e baixar.
- Tema escuro/claro na casca principal, preservando o workspace compacto do Editor Pro.

## Hardware Auto 2.0

O Hardware Manager detecta GPU, encoders do FFmpeg, RAM e CPU, e cria um perfil ECO/BALANCEADO/TURBO.

- **NVIDIA:** tenta faster-whisper em CUDA e render por NVENC; se CUDA não estiver utilizável, a transcrição cai para CPU.
- **AMD:** no Windows o BAT tenta preparar DirectML para transcrição e usa AMF quando o FFmpeg/driver oferecem `h264_amf`; existe fallback CPU/libx264.
- **Intel:** no Windows pode usar DirectML para IA e QSV para render quando disponíveis; caso contrário usa CPU.
- **CPU:** faster-whisper INT8 + libx264.

O arquivo `data/hardware_profile.json` guarda o diagnóstico local escolhido para a máquina.


## Hybrid Worker V3.2

Todo processamento pesado — FFmpeg, transcrição, Face Tracking, Auto Edit e render — é executado pelo **Local Worker**. O browser não renderiza o MP4 final. **WebGPU** acelera apenas canvas/preview quando disponível.

O gargalo de 10% foi removido mudando a ordem do pipeline: primeiro vem a **transcrição** e a seleção dos melhores trechos; só depois o **Face Tracking** analisa as janelas que realmente serão usadas. Cada job possui progresso, backend, ETA, heartbeat, pause/cancel/retry e recuperação após reinício.

## Biblioteca Leve / Asset Brain

A V3 mantém uma biblioteca reutilizável em:

```text
data/assets/
  broll/
  sfx/
  music/
  overlays/
  effects/
  filters/
  transitions/
  backgrounds/
  user/
  catalog.json
```

O preset **Leve** tem orçamento rígido de **2 GB**. O instalador gera localmente SFX, loops musicais e presets de efeitos/filtros/transições, e tenta completar a biblioteca com B-roll licenciado. Pexels e Pixabay são opcionais via chaves próprias (`PEXELS_API_KEY` / `PIXABAY_API_KEY`); sem chaves, o instalador possui um fallback de mídia compatível com o catálogo local. Cada asset guarda origem, licença e atribuição no `catalog.json`.

O sistema não força um B-roll sem relação: se a busca local não tiver resultado suficientemente compatível, mantém o vídeo principal.

## Auto Edit / Director AI

Na criação de um projeto, **Auto Edit** pode ficar ligado desde o início. Depois que o Whisper gera a transcrição, o Director AI divide o texto em trechos, interpreta conceitos e monta uma edição não destrutiva na Timeline Pro.

Ele pode decidir automaticamente:

- B-roll por contexto da frase;
- impacto/whoosh/riser e outros SFX;
- música de fundo em volume baixo;
- zoom punch, smart zoom, shake, flash e blur;
- filtro global apropriado ao estilo;
- markers para hook, B-roll e ênfases.

Estilos iniciais: Podcast Viral, Notícias, Política, Finanças, Fofoca, Documentário, Gaming, Storytelling e Viral acelerado. Intensidades: Clean, Normal, Viral e Hyper.

Todas as decisões aparecem no editor antes do render final e podem ser removidas ou alteradas.

## Timeline Pro · Schema V3

Cada clipe possui uma timeline persistida em SQLite com `schemaVersion: 3` e tracks independentes:

```text
Vídeo
B-roll
Legendas
Texto
Overlays
SFX
Música
Efeitos
```

Itens guardam `from`, `duration`, asset, volume, opacidade, efeito e metadados. O editor mostra as lanes visualmente; clicar em um item move o playhead até ele. A Biblioteca permite buscar materiais e inseri-los no ponto atual.

A Timeline V3 convive com o editor legado da V2.2: layout, Caption Engine, Brand Kit e cues continuam funcionando.

## Render da timeline

O renderer cria primeiro a base com Layout Engine + Caption Engine + Brand Kit. Depois compõe B-roll, filtros, efeitos e áudio da Timeline Pro com FFmpeg.

- B-roll é recortado/escalado para a composição e aplicado apenas no intervalo escolhido.
- SFX e música entram via mix de áudio com delay e volume independentes.
- Música pode repetir até o final do clipe.
- Zoom, shake, flash e blur usam filtros procedurais, sem depender de arquivos grandes.
- Preview e render final usam a mesma timeline.

O encoder é escolhido automaticamente entre `h264_nvenc`, `h264_amf`, `h264_qsv` e `libx264`.

## Editor Pro

O editor possui player limpo, safe zones, legendas editáveis, layouts, CTA/Brand Kit, Auto Edit, Biblioteca Local e Timeline Pro. A legenda não é duplicada: o vídeo usado no editor é limpo e as camadas só são queimadas no preview/render.

Entre os recursos preservados da V2.2 estão:

- 17 layouts com Face Tracking e fallbacks;
- aspect ratios 9:16 (**1080×1920**), 4:5 (**1080×1350**), 1:1 (**1080×1080**) e 16:9 (**1920×1080**);
- Caption Engine com ASS/libass, Word Pop, Scaling Words, Karaoke e Rainbow;
- edição de texto e timestamps da legenda;
- undo/redo e autosave;
- Brand Kit e overlays;
- Editor em Massa;
- render em fila e recuperação de trabalhos interrompidos com **Reprocessar projeto**.

## Entrada de vídeo

- upload MP4/MOV/MKV/AVI;
- YouTube e outras URLs suportadas pelo yt-dlp;
- Twitch/Kick/Google Drive quando o backend consegue normalizar a fonte;
- Smart Clip, Sequencial e timestamps manuais;
- escolha de layout e Auto Edit antes do processamento.

Use apenas conteúdo que você tem direito de baixar e processar.

## API local v1 / Worker-ready

A aplicação expõe uma API local versionada. Entre os endpoints iniciais:

```text
GET  /api/v1/health
GET  /api/v1/capabilities
GET  /api/v1/assets
GET  /api/v1/assets/status
GET  /api/v1/clips/{id}/timeline
PUT  /api/v1/clips/{id}/timeline
POST /api/v1/clips/{id}/auto-edit
```

`/api/v1/health` é público para descoberta local; dados de projeto/asset/timeline exigem a sessão autenticada. A API informa versões do protocolo, schema da timeline e capabilities do computador.

Essa separação deixa o motor pronto para, futuramente, uma interface hospedada na Vercel controlar um **Local Worker** no PC do usuário sem transformar a Vercel em render farm. A V3.2 inclui **Worker Protocol v1** com pairing local, jobs persistentes e controles. A futura interface Vercel pode usar esse contrato para comandar o PC sem transformar a Vercel em render farm.

## Configuração opcional

`.env` pode configurar um LLM OpenAI-compatible/LM Studio:

```env
LLM_BASE_URL=http://localhost:1234/v1
LLM_API_KEY=lm-studio
LLM_MODEL=seu-modelo
```

E provedores extras de B-roll:

```env
PEXELS_API_KEY=
PIXABAY_API_KEY=
```

Nenhuma chave é obrigatória para abrir o ViralClip.

## Diagnóstico

Use:

```bat
VIRALCLIP.bat diagnose
```

O diagnóstico mostra Python, **Hardware Auto 2.0**, GPU/encoder verificado, backend de transcrição, FFmpeg, yt-dlp, Face Tracking por janela, Local Worker e estado da **Biblioteca Leve**.

## Migração da V2.2

Para primeiro teste, extraia a V3 em **pasta nova**. Projetos novos já recebem Timeline Schema V3 e podem ativar Auto Edit. A estrutura V2.2 de editor/render continua presente para compatibilidade e fallback.

Leia também `docs/V3.2_RELEASE_NOTES.md` e `docs/V3_RELEASE_NOTES.md` e a especificação em `docs/superpowers/specs/2026-08-16-viralclip-studio-v3-design.md`.
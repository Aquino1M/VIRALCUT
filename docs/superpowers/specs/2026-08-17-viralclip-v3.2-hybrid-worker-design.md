# ViralClip Studio V3.2 — Hybrid Worker Edition

Data: 2026-08-17
Base: ViralClip Studio V3.1.0
Status: design aprovado em conversa; aguardando revisão da especificação escrita antes do plano de implementação.

## 1. Objetivo

Eliminar o travamento percebido em 10% e transformar a V3.1 em uma arquitetura híbrida pronta para uso local hoje e integração com um frontend hospedado na Vercel depois.

Princípio central:

- navegador/Vercel: interface, timeline, canvas, preview visual e WebGPU quando disponível;
- ViralClip Local Worker: toda tarefa pesada de vídeo/IA;
- arquivos grandes permanecem no computador do usuário por padrão;
- GPU/CPU do usuário é detectada, testada e escolhida automaticamente;
- nenhuma etapa pode ficar silenciosamente parada sem heartbeat, progresso, ETA ou fallback.

## 2. Causa-raiz do travamento atual

Na V3.1, `process_project()` executa `face_tracking.analyze_video()` logo após o ingest e antes da transcrição. `analyze_video()` abre o vídeo no OpenCV e decodifica sequencialmente o arquivo até o fim, mesmo que só mantenha amostras a uma taxa reduzida. Em vídeos longos, a etapa marcada como 10% pode consumir dezenas de minutos antes de qualquer progresso adicional visível.

A V3.2 remove esse desenho. O tracking completo deixa de ser um pré-requisito global do projeto.

## 3. Novo pipeline

Fluxo padrão:

1. validar fonte e espaço em disco;
2. detectar/revalidar hardware e perfil;
3. ingerir o vídeo ou registrar arquivo local;
4. extrair/probe de áudio e metadados;
5. transcrever com backend escolhido pelo Hardware Manager;
6. detectar cenas, silêncios, mudanças relevantes e candidatos de corte;
7. selecionar os cortes;
8. executar Face Tracking somente nas janelas dos cortes escolhidos, com pequena margem temporal;
9. montar Layout Engine + Caption Engine + Auto Edit;
10. gerar proxy/preview;
11. renderizar saída final sob demanda ou conforme configuração;
12. persistir artefatos, progresso e cache.

Para um vídeo de duas horas que gere cinco cortes de sessenta segundos, o tracking deixa de analisar duas horas e passa a analisar aproximadamente cinco minutos mais margens.

## 4. Local Worker obrigatório para tarefas pesadas

O Worker será a fonte de verdade de processamento. Mesmo quando a UI estiver hospedada na Vercel, as seguintes tarefas sempre vão para o Worker:

- ingest local e downloads pesados;
- FFmpeg/ffprobe;
- transcrição;
- scene detection;
- Face Tracking/active-speaker heurístico;
- Auto Edit/Asset Brain local;
- composição da timeline;
- geração de proxies de alta fidelidade;
- render final;
- exportação em lote;
- cache e arquivos temporários.

O frontend nunca deve depender de uma Vercel Function para transportar o vídeo original inteiro.

## 5. WebGPU no navegador

WebGPU será aceleração de experiência, não motor de render final.

Responsabilidades:

- canvas do editor;
- preview de crop/layout;
- preview de filtros compatíveis;
- transformações leves de elementos;
- thumbnails/frames já disponibilizados pelo Worker;
- visualização de waveform e efeitos de UI.

Fallbacks: WebGL e Canvas 2D. A ausência de WebGPU não bloqueia criação de cortes ou render final.

## 6. Hardware Auto 2.0

O Worker cria um `hardware_profile.json` versionado e revalida quando driver, GPU, FFmpeg ou ambiente mudarem.

Detecção mínima:

- sistema operacional;
- CPU, threads e memória;
- GPUs presentes e GPU preferida;
- VRAM quando possível;
- espaço livre;
- FFmpeg e encoders realmente disponíveis;
- CUDA/CTranslate2 quando aplicável;
- DirectML/Vulkan/OpenVINO quando aplicável;
- NVENC/AMF/QSV por teste real, não somente presença no texto de `ffmpeg -encoders`.

Rotas preferidas:

- NVIDIA: CUDA para transcrição compatível, NVENC para vídeo;
- AMD Windows: DirectML ou backend local compatível para IA, AMF para vídeo;
- Intel: OpenVINO/DirectML conforme disponibilidade, QSV para vídeo;
- CPU: modelos quantizados/INT8 e libx264.

Toda rota possui fallback. Uma capability anunciada que falhar no benchmark é marcada como indisponível até nova revalidação.

## 7. Perfis adaptativos

Perfis iniciais:

- ECO: baixa concorrência, tracking reduzido, proxy leve;
- BALANCEADO: padrão recomendado;
- RÁPIDO: usa mais recursos sem saturação prolongada;
- TURBO: máximo paralelismo permitido pelo benchmark.

O perfil controla modelo de transcrição, threads, resolução de análise, FPS de tracking, renders paralelos e escala do proxy. O usuário pode escolher um perfil, mas não precisa configurar CUDA/AMF/QSV manualmente.

## 8. Scheduler adaptativo

O Worker monitora CPU, RAM, GPU quando mensurável e espaço em disco durante jobs. Ele pode reduzir concorrência e qualidade de análise antes de causar paginação excessiva, OOM ou congelamento.

Decisões automáticas devem ser registradas no job, por exemplo: `tracking_fps 2.0 -> 1.0 por pressão de CPU`.

## 9. Face Tracking 3.0

O tracking passa a operar por `clip_window`, não por projeto inteiro.

Estratégia:

- scene boundaries primeiro;
- leitura apenas entre `start-margin` e `end+margin`;
- downscale de análise configurado pelo perfil;
- detecção em amostras e interpolação/smoothing entre keyframes;
- IDs por cena e associação temporal;
- activity score leve para enquadramento de falante;
- cache por hash da fonte + janela + versão do algoritmo + configurações;
- fallback para safe crop quando nenhum rosto for detectado.

O tracking é sempre tentado, mas nunca pode bloquear indefinidamente um projeto.

## 10. Watchdog anti-travamento

Cada job e cada etapa possui:

- `stage`;
- `status`;
- `progress_current`/`progress_total`;
- percentual calculado;
- `started_at`;
- `heartbeat_at`;
- velocidade;
- ETA;
- backend;
- tentativa;
- mensagem amigável;
- detalhes técnicos opcionais.

Uma etapa sem heartbeat dentro da janela esperada entra em recuperação automática.

Sequência para tracking lento:

1. reduzir FPS de detecção;
2. reduzir resolução de análise;
3. trocar backend/detector compatível;
4. usar safe crop e continuar.

A UI deve mostrar o fallback; nunca congelar silenciosamente em 10%.

## 11. Progresso real

O percentual do projeto será derivado de trabalho medido, não de valores fixos isolados.

Exemplos:

- download: bytes recebidos / total quando disponível;
- transcrição: segundos transcritos / duração;
- tracking: segundos ou frames analisados / janela total;
- render: tempo FFmpeg processado / duração de saída;
- Auto Edit: decisões processadas / total de segmentos.

A página consulta um snapshot leve, mas o Worker também poderá oferecer stream de eventos no futuro.

## 12. Job Store persistente

SQLite passa a armazenar jobs e stages explicitamente, separados do status geral do projeto.

Estados de job:

`queued`, `running`, `paused`, `retrying`, `done`, `error`, `cancelled`, `interrupted`.

Ao iniciar o Worker:

- jobs `running` sem heartbeat são marcados como `interrupted`;
- etapas idempotentes podem ser retomadas;
- etapas não retomáveis são reiniciadas desde o último checkpoint seguro;
- arquivos de saída válidos nunca são apagados apenas porque a UI fechou.

## 13. Controles do usuário

Durante jobs:

- Pausar;
- Continuar;
- Cancelar;
- Tentar novamente;
- Pular etapa opcional quando houver fallback seguro;
- abrir detalhes técnicos;
- abrir arquivo/log relevante.

Cancelar deve encerrar subprocessos FFmpeg/Whisper filhos e limpar somente temporários pertencentes ao job.

## 14. Worker Protocol v1

Contrato local estável e versionado:

- `GET /api/v1/health`
- `GET /api/v1/capabilities`
- `POST /api/v1/pair`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{id}`
- `GET /api/v1/jobs/{id}/events`
- `POST /api/v1/jobs/{id}/pause`
- `POST /api/v1/jobs/{id}/resume`
- `POST /api/v1/jobs/{id}/cancel`
- `POST /api/v1/jobs/{id}/retry`
- `GET /api/v1/assets`
- `GET /api/v1/renders/{id}`

O estado persiste no Worker; a conexão do browser não é a fonte de verdade.

## 15. Pairing e segurança para futura Vercel

Modo local atual continua funcionando em loopback.

Para frontend hospedado:

- pairing explícito com código curto/QR;
- token local revogável por dispositivo;
- CORS allowlist configurável;
- requisições mutáveis assinadas/autenticadas;
- nenhuma API de arquivo aceita caminho arbitrário enviado pelo browser;
- Worker usa IDs de assets cadastrados e sandbox de diretórios;
- segredos do Worker nunca são enviados ao frontend hospedado;
- logs não devem incluir tokens, cookies ou URLs assinadas completas.

## 16. Cache inteligente

Chaves de cache incluem hash da fonte, intervalo, versão do algoritmo e configurações relevantes.

Caches separados:

- metadata/probe;
- áudio extraído;
- transcrição;
- scene map;
- tracking por janela;
- proxies;
- thumbnails;
- Auto Edit plan;
- render intermediário quando reutilizável.

Alterar legenda não invalida transcrição/tracking. Alterar layout invalida apenas artefatos dependentes do layout.

## 17. Disk Manager

Antes de iniciar job pesado:

- medir espaço livre;
- estimar temporários;
- bloquear início quando não houver margem segura;
- mostrar pasta e espaço usado;
- limpeza de temporários órfãos por idade;
- nunca apagar mídia importada do usuário automaticamente.

## 18. UI de processamento

A tela de projeto terá uma lista de etapas, não somente barra global.

Exemplo:

- Vídeo preparado ✓
- Hardware otimizado ✓
- Transcrição 64% — 18:42 / 29:11 — ETA 02:14
- Selecionar cortes ○
- Tracking dos cortes ○
- Auto Edit ○
- Render ○

Também mostra backend ativo, perfil e botão para abrir Hardware Local.

## 19. Hardware Local UI

Deve exibir fatos medidos:

- CPU/RAM;
- GPU e VRAM;
- backend de transcrição ativo;
- encoder final ativo;
- disponibilidade WebGPU reportada pelo browser separadamente;
- benchmark e data da última detecção;
- perfil atual;
- botão `Reavaliar hardware`.

Não deve afirmar aceleração GPU apenas porque o fabricante da placa foi detectado.

## 20. Launcher único

`VIRALCLIP.bat` permanece o ponto de entrada principal.

Ele deve:

- instalar/atualizar dependências necessárias;
- verificar Python/uv;
- verificar FFmpeg;
- detectar hardware;
- executar benchmark quando necessário;
- preparar modelos/assets essenciais;
- iniciar Worker;
- esperar `/health` responder;
- abrir UI local;
- registrar erro amigável se a inicialização falhar.

Flags avançadas podem existir, mas o fluxo normal continua sendo duplo clique.

## 21. Auto Edit e Asset Brain

A V3.2 mantém a Biblioteca Leve (~2 GB), mas o Director AI passa a respeitar o scheduler e os jobs persistentes.

B-roll, música, SFX, filtros, transições e efeitos continuam definidos como itens de timeline. Downloads opcionais entram em jobs próprios e registram origem/licença no catálogo.

## 22. Melhorias adicionais de qualidade

Entram junto porque servem diretamente ao fluxo híbrido:

- proxy imediato de baixa resolução após ingest;
- preview de 3–5 s para mudança de layout/efeito pesado;
- render parcial de faixa selecionada;
- deduplicação por hash de fonte;
- fila com prioridade (`interactive`, `normal`, `background`);
- limite de subprocessos pesados por perfil;
- desligamento gracioso do Worker;
- diagnóstico exportável sem dados privados;
- botão `Copiar diagnóstico` para suporte;
- mensagens de erro com ação recomendada;
- retry exponencial somente para operações de rede;
- retenção configurável de temporários e proxies.

## 23. Compatibilidade V3.1

Projetos V3.1 continuam abrindo.

Migração:

- settings antigos são normalizados;
- `tracking_path` global existente pode ser lido como cache legado;
- novos jobs/stages são criados apenas para trabalhos novos/reprocessados;
- nenhum banco do usuário é descartado automaticamente.

## 24. Testes obrigatórios

Antes da entrega:

- regressão: projeto longo não executa tracking global antes da transcrição;
- unit: seleção de backend NVIDIA/AMD/Intel/CPU com fallbacks;
- unit: benchmark falho desabilita capability anunciada;
- unit: tracking por janela não lê além do intervalo necessário, salvo margem definida;
- unit: watchdog aplica degradação e depois safe crop;
- unit: heartbeat/ETA/progresso por stage;
- unit: persistência/recovery de jobs;
- unit: pause/resume/cancel/retry;
- unit: cache keys e invalidação seletiva;
- security: path traversal e origem CORS/pairing;
- integration: transcrição -> candidatos -> tracking por clips -> Auto Edit -> render;
- FFmpeg smoke com CPU e encoder de hardware quando disponível no ambiente;
- ZIP extraído: suíte completa + compileall + smoke render;
- nenhum segredo, banco, mídia de usuário, fonte binária, cache ou credencial no pacote.

## 25. Critérios de aceite

A V3.2 é aceita quando:

1. um vídeo longo começa transcrição antes de qualquer tracking detalhado;
2. o tracking detalhado ocorre somente para cortes candidatos/finais;
3. toda etapa pesada envia heartbeat e progresso mensurável;
4. uma falha de tracking continua com fallback em vez de congelar;
5. hardware escolhido é resultado de detecção + teste real;
6. fechar/reabrir UI não interrompe job;
7. reiniciar Worker recupera ou marca trabalho interrompido de forma acionável;
8. frontend consegue controlar jobs somente por Worker Protocol v1;
9. V3.1 continua compatível;
10. pacote final passa a verificação a partir do próprio ZIP extraído.

## 26. Fora do escopo desta versão

- render pesado dentro da Vercel;
- upload obrigatório do vídeo original para cloud;
- treinamento de modelos próprios;
- sincronização multi-PC completa;
- aplicativo móvel nativo;
- publicação automática em redes sociais sem integração específica futura.

Esses itens não são necessários para resolver o gargalo atual ou preparar a integração Vercel + Local Worker.

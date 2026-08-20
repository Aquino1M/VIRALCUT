# ViralClip Studio V3.2 Hybrid Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Eliminar o travamento em 10%, mover todo processamento pesado para um Worker local persistente e adaptar automaticamente o pipeline ao hardware NVIDIA/AMD/Intel/CPU do usuário.

**Architecture:** O frontend continua sendo a UI do produto e usa WebGPU/WebGL/Canvas apenas para preview. O Worker local é a fonte de verdade para jobs, FFmpeg, transcrição, tracking, Auto Edit e render. O pipeline passa a transcrever/selecionar cortes antes de rastrear rostos, e o tracking opera somente em janelas de corte com watchdog/fallback.

**Tech Stack:** FastAPI/Starlette, SQLite, Python 3.10–3.12, OpenCV, faster-whisper/DirectML fallbacks, FFmpeg/ffprobe, Jinja2, JavaScript browser APIs, Windows BAT.

## Global Constraints

- Base: ViralClip Studio V3.1.0.
- Worker obrigatório para tarefas pesadas; navegador nunca renderiza o vídeo final.
- WebGPU é opcional e possui WebGL/Canvas fallback.
- Nenhuma etapa pode ficar sem heartbeat/progresso indefinidamente.
- Tracking é sempre tentado por janela de corte e possui safe-crop fallback.
- NVIDIA/AMD/Intel/CPU devem funcionar com fallback automático.
- Arquivos grandes permanecem locais por padrão.
- Não armazenar tokens/cookies em logs ou respostas de API.

---

### Task 1: Job Store persistente e progresso real

**Files:**
- Modify: `app/db.py`
- Create: `app/services/job_store.py`
- Test: `tests/test_v32_job_store.py`

**Interfaces:**
- Produces: `create_job()`, `start_stage()`, `update_stage()`, `finish_stage()`, `fail_stage()`, `job_snapshot()`, `recover_stale_jobs()`.

- [x] Escrever testes que exigem tabelas `worker_jobs`/`worker_job_stages`, heartbeat, ETA e recuperação de jobs `running` obsoletos.
- [x] Rodar `pytest tests/test_v32_job_store.py -q` e confirmar falha por API/tabelas ausentes.
- [x] Implementar migrações idempotentes e `job_store.py` com snapshots JSON-safe.
- [x] Rodar o teste novamente e confirmar PASS.
- [x] Commitar `feat: add persistent worker job store`.

### Task 2: Hardware Auto 2.0 e perfil executável

**Files:**
- Modify: `app/services/hardware.py`
- Modify: `tools/setup_acceleration.py`
- Test: `tests/test_v32_hardware_auto.py`

**Interfaces:**
- Produces: `build_hardware_profile()`, `load_or_build_profile()`, `transcription_route()`, `render_route()`.

- [x] Escrever testes para NVIDIA/NVENC/CUDA, AMD/AMF/DirectML, Intel/QSV/OpenVINO e CPU/libx264, incluindo capability anunciada mas benchmark reprovado.
- [x] Confirmar RED.
- [x] Implementar perfil versionado, `analysis_width`, `tracking_fps`, modelo Whisper, threads e `max_parallel_renders`.
- [x] Confirmar GREEN e regressão de hardware V3.
- [x] Commitar `feat: add hardware auto 2 profile`.

### Task 3: Face Tracking 3.0 por janela

**Files:**
- Modify: `app/services/face_tracking.py`
- Test: `tests/test_v32_tracking_windows.py`

**Interfaces:**
- Produces: `analyze_window(video_path, start, end, ..., progress_callback=None, cancel_check=None)` e `merge_window_tracks()`.

- [x] Escrever teste que garante seek para janela, timestamps absolutos, progresso crescente e cache por fonte+janela+config.
- [x] Confirmar RED.
- [x] Implementar leitura limitada à janela, downscale por perfil, amostragem/interpolação e fallback existente.
- [x] Confirmar GREEN.
- [x] Commitar `feat: track only selected clip windows`.

### Task 4: Reordenar pipeline e remover tracking global em 10%

**Files:**
- Modify: `app/services/jobs.py`
- Modify: `app/services/projects.py`
- Test: `tests/test_v32_pipeline_order.py`

**Interfaces:**
- Consumes: `job_store`, `hardware.load_or_build_profile()`, `face_tracking.analyze_window()`.

- [x] Escrever teste que prova ordem `ingest -> transcribe -> highlights -> window tracking -> render` e que `analyze_video()` não é chamado no início.
- [x] Confirmar RED.
- [x] Implementar pipeline novo com pesos reais de progresso e tracking por candidato antes de cada render.
- [x] Atualizar `tracking_summary_json` como agregado das janelas processadas.
- [x] Confirmar GREEN e testes antigos de projetos/render.
- [x] Commitar `fix: remove full-video tracking bottleneck`.

### Task 5: Watchdog, pause/cancel/retry e recuperação

**Files:**
- Create: `app/services/worker_control.py`
- Modify: `app/services/jobs.py`
- Modify: `app/services/render_queue.py`
- Test: `tests/test_v32_worker_control.py`

**Interfaces:**
- Produces: `JobControl`, `heartbeat()`, `should_cancel()`, `wait_if_paused()`, `mark_retry()`.

- [x] Escrever testes para pause/resume/cancel, stale heartbeat e tracking degradado após timeout.
- [x] Confirmar RED.
- [x] Implementar controle cooperativo e checkpoints; subprocessos devem receber cancelamento onde o código atual permite.
- [x] Confirmar GREEN.
- [x] Commitar `feat: add worker watchdog and controls`.

### Task 6: Worker Protocol v1 completo

**Files:**
- Modify: `app/services/api_v1.py`
- Modify: `app/main.py`
- Test: `tests/test_v32_worker_protocol.py`

**Interfaces:**
- Endpoints: `/api/v1/health`, `/capabilities`, `/pair`, `/jobs`, `/jobs/{id}`, `/jobs/{id}/events`, `/pause`, `/resume`, `/cancel`, `/retry`.

- [x] Escrever testes HTTP para health/capabilities, criação/leitura de job e controles.
- [x] Confirmar RED.
- [x] Implementar endpoints e payloads sem expor caminhos arbitrários ou segredos.
- [x] Confirmar GREEN.
- [x] Commitar `feat: complete worker protocol v1`.

### Task 7: UI híbrida, progresso detalhado e WebGPU capability

**Files:**
- Modify: `app/templates/project.html`
- Modify: `app/templates/hardware.html`
- Modify: `app/templates/base.html`
- Modify: `app/static/shell.js`
- Modify: `app/static/style.css`
- Test: `tests/test_v32_worker_ui.py`

**Interfaces:**
- UI consome `/api/v1/jobs/{id}` e `/api/v1/capabilities`.

- [x] Escrever testes de contrato HTML/JS exigindo status Worker, backend, etapa, ETA, heartbeat, pause/cancel/retry e detecção WebGPU com fallback.
- [x] Confirmar RED.
- [x] Implementar cards de progresso e Worker; projeto deixa de mostrar só percentual fixo sem contexto.
- [x] Confirmar GREEN e testes V3.1 shell/editor.
- [x] Commitar `feat: add hybrid worker progress ui`.

### Task 8: Launcher único, release e verificação de pacote

**Files:**
- Modify: `VIRALCLIP.bat`
- Modify: `VERSION`
- Modify: `README.md`
- Modify: `ARQUITETURA.md`
- Create: `docs/V3.2_RELEASE_NOTES.md`
- Test: `tests/test_v32_release_contract.py`

**Interfaces:**
- `VIRALCLIP.bat` prepara/revalida hardware e inicia Worker/UI.

- [x] Escrever teste de release para versão 3.2.0, launcher único e artefatos proibidos no ZIP.
- [x] Confirmar RED.
- [x] Atualizar launcher/documentação/release notes.
- [x] Rodar `pytest -q`, `python -m compileall -q app tools run.py`, validação JS e smoke FFmpeg.
- [x] Gerar ZIP apenas de arquivos versionados; extrair em diretório limpo e repetir suíte/compile/smoke.
- [x] Commitar `release: ViralClip Studio 3.2.0`.


## Verification record

- Full source-tree suite: 222 tests passed.
- Python compileall: passed.
- JavaScript syntax checks: shell/editor/bulk passed.
- Real 8-second Face Tracking window smoke: window-sequential, 9 samples, completed successfully.
- Real 5-second FFmpeg render smoke: H.264 1080x1920 with local CPU fallback in the verification environment.
- Final extracted-ZIP verification is performed after the release commit/archive.

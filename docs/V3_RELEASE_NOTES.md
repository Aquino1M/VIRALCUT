# ViralClip Studio V3.1 — Release Notes

A V3.1 é uma evolução local-first da **V2.2**. O pipeline de cortes, face tracking, layouts, legendas e FFmpeg continua sendo a base, mas agora existe uma Timeline Schema V3, Asset Brain, Auto Edit e um Hardware Manager universal.


## Studio Shell V3.1

- Tela de Novo Projeto source-first: link ou drag-and-drop antes das configurações avançadas.
- Cards de layout e Auto Edit permanecem disponíveis antes de iniciar o processamento.
- Sidebar desktop por fluxo e navegação mobile com botão central de criação.
- Novas áreas: Meus Vídeos, Biblioteca Inteligente, Templates, Brand Kit e Hardware Local.
- O material externo fornecido como referência foi usado apenas para entender padrões de UX/estrutura; credenciais, tokens, dados pessoais, assets e código proprietário não fazem parte do ViralClip.
- `VIRALCLIP.bat` continua sendo a única entrada recomendada; BATs antigos ficam apenas por compatibilidade/diagnóstico avançado.

## Principais mudanças

- Um único `VIRALCLIP.bat` para instalar, diagnosticar, reparar, atualizar e iniciar.
- Detecção de NVIDIA/AMD/Intel/CPU com NVENC/AMF/QSV/libx264 e fallbacks.
- Transcrição automática: NVIDIA tenta CUDA; AMD/Intel Windows podem usar DirectML; CPU continua disponível.
- Biblioteca Leve com orçamento máximo de **2 GB**, armazenada em `data/assets/`.
- SFX, músicas, filtros, efeitos e transições procedurais criados localmente.
- B-roll local indexado por assunto, tags, origem e licença; provedores online são opcionais.
- Auto Edit lê a transcrição e gera uma edição não destrutiva com B-roll/SFX/música/filtros/efeitos.
- Timeline Pro com tracks para vídeo, B-roll, legendas, texto, overlays, SFX, música e efeitos.
- API local `/api/v1` preparada para separar interface e worker em uma futura integração SaaS/Vercel.

## Migração

Para testar a V3 pela primeira vez, use uma **pasta nova** e mantenha sua V2.2 intacta. Execute somente `VIRALCLIP.bat`. Projetos antigos não recebem Auto Edit silenciosamente; o recurso fica ligado por padrão apenas no formulário de novos projetos da V3, e continua sendo opcional.

A Biblioteca Leve não é embutida no ZIP para evitar distribuir gigabytes de mídia de terceiros. Na primeira execução, o instalador cria os assets próprios do ViralClip e baixa B-roll permitido diretamente para o computador do usuário, respeitando o teto de 2 GB e registrando licença/origem no catálogo.

## Compatibilidade

Python recomendado: 3.10–3.12. O sistema mantém fallback CPU e libx264, portanto uma falha de driver ou aceleração não deve impedir o editor de abrir. Use `VIRALCLIP.bat safe` para iniciar no modo conservador.

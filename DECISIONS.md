# Decisões de Design — KOLBIE SAMPLES Migration

Este documento existe pra não perder o raciocínio por trás de cada escolha do
pipeline. Sempre que uma regra parecer arbitrária, a resposta pro "por quê"
deveria estar aqui.

## Status

Código completo, todas as correções do piloto validadas. Aguardando execução
do Ciclo 1 completo (20.349 arquivos, `-ELETRONIC MUSIC-`, ~5h estimado).

## O quê / por quê

Migra 215.539 arquivos de áudio (406GB, 3 pastas fonte, 9.341 subpastas
aninhadas hoje) para `/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES` com estrutura
pesquisável por Gênero/Tipo/Classificação/BPM e metadados extraídos
automaticamente. **Originais nunca são movidos ou apagados — só copiados.**

## Ciclos (1 pasta por vez, com piloto dry-run antes de cada um)

1. `-ELETRONIC MUSIC-` (20.3k arquivos, 176GB) — piloto feito, pronto pra rodar
2. `SAMPLES ABLETON` (154k arquivos, 156GB)
3. `NEW SAMPLES N PRESETS` (41.2k arquivos, 74GB)

## Taxonomia Loop / Oneshot / FX (`audio_analyzer.py::_classify_sound_type`)

**Não é baseada em duração.** Um corte fixo de duração classificava sons
longos sem groove (sweeps, drones) como "Loop" incorretamente. Critério atual,
por comportamento:

- **Loop** — onsets regulares + similaridade de chroma início/fim (ponto de
  loop real)
- **Oneshot** — ≤2 onsets, decai a silêncio, curto
- **FX_Oneshot_Longo** — evento único longo sem repetição rítmica
  (sweep/riser/impacto/drone)

FX não tem tempo, então é organizado por pasta de duração
(`0-3s/3-8s/8-20s/20s+`) em vez de faixa de BPM.

## Supressão de BPM/Key por classificação (`_apply_suppression_rules`)

Passe final, sobrepõe qualquer fonte (nome de arquivo, tag ID3, análise):

- **BPM** só é mantido quando `classificação == Loop`. Tempo não é
  propriedade de um evento único — antes vazava BPM fabricado tipo
  `[287 bpm]` num kick de 0.5s.
- **Key** é anulada só quando `tipo == Drums E classificação == Oneshot`
  (percussão sem afinação — análise de chroma sempre inventa uma nota
  mesmo pra um clap).
- Nome de arquivo omite o colchete `[bpm]`/`[key]` inteiro quando nulo, em
  vez de mostrar um placeholder `[_]`.
- Confiança se adapta aos campos que realmente se aplicam — um oneshot não
  é penalizado por corretamente não ter BPM.

## Brilho espectral (`_classify_brightness`, campo `brightness`)

Escuro / Medio / Claro / Full_Spectro — energia distribuída entre 3 faixas
de frequência (grave <250Hz, médio 250-4000Hz, agudo >4000Hz;
`config/genre_mapping.json` → `brightness_bands`). Se uma faixa domina
(≥45% da energia) herda o rótulo dela; senão vira Full_Spectro. Sempre
calculado (diferente de bpm/key, timbre existe em qualquer som). Validado
com casos de sanidade: prato ride → Claro, piano em C0 → Escuro, percussão
ruidosa → Full_Spectro.

## Bugs encontrados e corrigidos

- **`librosa.beat.tempo(onset_env=...)`** — kwarg renomeado + função
  realocada na v0.11 do librosa. Um `except` genérico engolia o erro
  silenciosamente — cobertura de BPM foi de 25% → 96.5% depois de trocar
  pra `librosa.feature.tempo(onset_envelope=...)`. **Lição**: sempre logar
  a exceção real em `except` genérico ao redor de chamada de biblioteca,
  senão bugs de version drift passam despercebidos indefinidamente.
- **`_extract_type_from_name`** lia o caminho completo em vez de só o nome
  do arquivo — nome de pasta pai (ex: `.../Future Bass Track/...`)
  contaminava a detecção de tipo (`PML_crash.wav` virava tipo Bass).
  Corrigido pra ler só o basename. Extração de gênero continua lendo o
  caminho completo de propósito (gênero geralmente só aparece em nome de
  pasta). `bpm`/`key` por regex no nome têm a mesma exposição teórica mas
  não foram tocados — fora do escopo aprovado até agora.

## Diagnóstico de arquivos rejeitados (`diagnose_rejected.py`)

Amostra com seed=42: 100% das rejeições são corrupção real e irrecuperável
(nada de "extensão errada" nem "recuperável via ffmpeg") — na maioria
arquivos placeholder 100% zero-byte (download/cópia interrompida). **100%
rastreado a 5 pastas específicas da marca "Exotic Refreshment"** — scan
completo dessas 5 pastas achou 919/962 arquivos corrompidos (95.5%). O
resto da pasta (~19.387 arquivos) está limpo. Conclusão: não precisa de
etapa de pré-conversão, o Ciclo 1 pode rodar como está.

## Performance: paralelismo com auto-calibração (`--parallel-workers`)

**Evolução em 2 rodadas.** Primeiro implementei paralelismo só na fase de
análise com um número fixo (4 workers), tuned manualmente num benchmark
dedicado nesta máquina/disco (Apple M1 Pro 8 núcleos + HD externo USB).
Resultado: 5.05x mais rápido (17.52 arq/s vs 3.47 sequencial), com 6 workers
sendo *pior* que 4 (contenção de leitura no HD, não CPU saturando).

**Problema do número fixo**: 4 foi tuned pra esta máquina + este disco
específicos. Rodar em outro computador, ou trocar de HD, invalidaria o
número sem re-benchmarkar manualmente — o oposto de "pronto pra rodar em
qualquer computador, qualquer HD".

**Solução: auto-calibração** (`modules/benchmark.py`). Antes de cada rodada
real, o script testa alguns números de workers candidatos (baseados na
contagem de núcleos: `{1, cpu//2, cpu-1, cpu}`) contra uma amostra real dos
arquivos desta pasta, neste disco, agora — e usa o mais rápido. Roda pra
**validação** (threads, já que é I/O-bound) e **análise** (processos,
CPU-bound) de forma independente, já que podem ter ótimos diferentes.

**Dois cuidados metodológicos, achados rodando e comparando com meu
benchmark manual anterior**:
1. *Amostra igual por candidato.* Deixar o candidato de 8 workers processar
   mais arquivos que o de 1 (pra "dar tempo" de amostrar) distorce a
   comparação — o candidato maior amortiza seu próprio custo de startup
   (mais processos pra importar bibliotecas) melhor que o menor, parecendo
   mais rápido por motivo errado, não por throughput real.
2. *Arquivos diferentes por candidato.* Reusar o mesmo arquivo pros 4
   candidatos faz só o primeiro pagar leitura real de disco — os seguintes
   pegam cache do SO, inflando artificialmente candidatos testados depois.
   Cada candidato agora lê um pedaço não-sobreposto do disco.

**Achado que só a calibração real revela** (não teria adivinhado por
intuição): calibrando a fase de validação pela etapa de hash MD5 (leitura
do arquivo inteiro, não só o cabeçalho), **1 thread às vezes venceu 8**
neste HD específico — leitura concorrente de arquivos grandes pode ser
pior que sequencial num disco mecânico (mais movimento de cabeça de
leitura entre arquivos intercalados). Contraria a suposição comum de "I/O
sempre se beneficia de paralelismo" — motivo exato de calibrar em vez de
fixar um número.

**Uso**: `--parallel-workers` default agora é `'auto'` (calibra sozinho,
~30-60s de overhead antes da rodada real — irrelevante numa rodada de
horas). Passar um inteiro explícito pula a calibração (útil em testes
rápidos repetidos, onde os 30-60s pesam proporcionalmente mais).

**Estimativa do Ciclo 1**: com os workers calibrados automaticamente, ~2h +
~1min de calibração (era ~3.2-4h sem paralelismo nenhum). Ciclo 2 (Ableton,
153.977 arquivos) deixou de ficar bloqueado só pela validação sequencial,
já que ela também está paralelizada agora — tempo exato depende do que a
calibração encontrar naquele disco/pasta específica.

## Notas de colaboração

- Revisão de relatório piloto → brief estruturado com mudanças numeradas →
  implementação exata do que foi pedido → validação → aprovação antes de
  escalar pro ciclo completo.
- Achados fora do escopo aprovado são sinalizados mas não corrigidos até
  aprovação explícita.

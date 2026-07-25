# Decisões de Design — KOLBIE SAMPLES Migration

Este documento existe pra não perder o raciocínio por trás de cada escolha do
pipeline. Sempre que uma regra parecer arbitrária, a resposta pro "por quê"
deveria estar aqui.

## Status

Dois pipelines completos: áudio (`migrate_samples.py`, já rodou o Ciclo 1
uma vez, corrigido e pronto pra rodar de novo) e MIDI+Presets
(`migrate_midi_presets.py`, construído do zero nesta sessão). Ambos
testados via dry-run e cópia real nas 3 pastas fonte. Destinos esvaziados,
aguardando execução completa.

## O quê / por quê

Migra 215.539 arquivos (406GB, 3 pastas fonte, 9.341 subpastas aninhadas
hoje) para duas árvores de destino separadas e pesquisáveis:
`KOLBIE SAMPLES` (áudio, por Gênero/Tipo/Classificação/BPM) e
`KOLBIE PRESETS:MIDI` (MIDI+Presets, por Gênero/Categoria/...).
**Originais nunca são movidos ou apagados — só copiados.**

## Ciclos (1 pasta por vez, com piloto dry-run antes de cada um)

1. `-ELETRONIC MUSIC-` (20.3k arquivos áudio + 2.6k MIDI/presets, 176GB)
2. `SAMPLES ABLETON` (120k arquivos áudio + 9.4k MIDI/presets, 156GB)
3. `NEW SAMPLES N PRESETS` (29k arquivos áudio + 9.2k MIDI/presets, 74GB)

---

# Pipeline de áudio

## Ordem de prioridade da informação (nome/pasta > metadado > áudio)

Decisão explícita do usuário (2026-07-25), vale pra **todos** os campos
(BPM, key, gênero, tipo, classificação), não só classificação: **o texto do
nome do arquivo e da pasta é buscado primeiro e é a fonte majoritária;
metadado embutido (tag ID3/WAV/AIFF) só preenche o que sobrar; análise de
áudio é o último recurso**, usada só quando nem o texto nem o metadado
já resolveram — o que também economiza processamento numa biblioteca de
150k+ arquivos (pula as partes caras da análise — contagem de picos,
estimativa de tempo, chroma — quando o texto já decidiu).

Por quê metadado vem depois do nome, e não antes: tags ID3 nesta
biblioteca são preenchidas de forma inconsistente (muitas em branco,
algumas geradas automaticamente pela ferramenta/DAW que exportou o
arquivo) e às vezes trazem valor não-curado (ex. uma tag de gênero
"Melodic House & Techno" que não bate com a taxonomia curada desta
biblioteca) — o nome que o sound designer/pack deu ao arquivo tende a ser
mais confiável.

Implementado em `AudioAnalyzer.analyze_file`: Passo 1 (nome/pasta) roda
primeiro e escreve os campos; Passo 2 (metadado) só preenche o que ainda
estiver `None`; Passo 3 (áudio) é o fallback final, com os mesmos guards
de "só computa o que falta" de antes.

## Taxonomia Loop / Oneshot / FX

**Não é baseada em duração pura.** Um corte fixo de duração classificava sons
longos sem groove (sweeps, drones) como "Loop" incorretamente.

### Passo 1 — texto do nome/caminho tem prioridade (`_classify_from_path`)

Roda antes de qualquer análise de áudio (ver seção acima). Verifica o
caminho inteiro — pasta E nome do arquivo — pra ambas as palavras-chave,
nessa ordem:

1. **"one-shot"/"oneshot"** primeiro, sem nenhuma outra condição além de
   existir no texto. Medido contra as 171.337 arquivos de áudio reais das
   3 pastas fonte antes de implementar (não convém supor, ver
   [[feedback_data_pipeline_workflow]]): zero contra-exemplos encontrados
   em toda a amostra (pasta ou nome do arquivo) — ex. `Diginoiz_Kick.wav`
   dentro de uma pasta `(One-Shots)` é genuinamente um one-shot mesmo sem
   repetir a palavra no próprio nome. 5.354 matches no basename + 20.342
   só na pasta, os dois grupos confirmados.
2. **"loop"** segundo, e só se `duration >= min_loop_duration_seconds`
   (o mesmo piso arquitetural que `_classify_sound_type` já usa — nada
   abaixo de ~1.5s pode ser um loop musical real nesse range de BPM da
   biblioteca). Esse único piso já resolveu os contra-exemplos reais
   achados: `Maschine Samples/Loops/Synth/Galbanum12 [128] 36.wav` e
   `.../Loops/Percussion/Tabla/Tabla02 [130] 03.wav` têm 0.20-0.22s de
   duração — fisicamente impossível ser loop, são one-shots dentro de uma
   pasta "Loops" que é só a categoria interna da biblioteca Maschine, não
   uma descrição real do conteúdo. Fora esse piso de duração, decisão do
   usuário: bibliotecas/publicadoras raramente colocam one-shots dentro de
   uma pasta categorizada como loop, então a pasta conta tanto quanto o
   nome do arquivo — 23.620 matches no basename + 27.028 só na pasta;
   amostra real de 30 arquivos (decodificados de verdade) achou 77%
   (23/30) já corretos como Loop pela própria análise de áudio, e os únicos
   contra-exemplos claros eram sub-piso de duração.
   - Checar "one-shot" primeiro resolve sozinho o conflito de
     `Prime Loops Synthwave 2 MULTiFORMAT/One Shots/FX/PhaserWaves_FX.wav`:
     "Loops" está no nome do *pack* várias pastas acima, mas a pasta
     imediata do arquivo já diz "One Shots/FX" — como one-shot é checado
     primeiro, o check de loop nem chega a rodar pra esse caminho.
   - *(Nota: uma versão anterior deste documento citava
     `RETRO FUTURE/drum loops/rf_drm130_doggie_hat.wav` como prova de que
     pasta-só-com-"loop" não era confiável — errado, checado com áudio
     real depois que o usuário ouviu o arquivo e confirmou que É um loop
     [3.69s = exatos 2 compassos a 130 BPM]. O erro foi inferir do nome do
     arquivo ["doggie_hat" soa como um hit de hi-hat] sem nunca checar o
     áudio de verdade. Corrigido pro exemplo Maschine Samples acima, que
     não depende de interpretação nenhuma — a duração sozinha já prova.)*
- Regex com fronteira de palavra (`\bloops?\b`, `\bone\s?shots?\b`) sobre o
  texto normalizado (`_`/`-` viram espaço, já que o padrão de nomenclatura
  da biblioteca junta palavras assim e isso quebra `\b` do jeito ingênuo) —
  não casa "loophole" nem falha em "One_Shots_Sub_Bass".
- **Guarda defensiva**: os 3 nomes de pasta de classificação que o próprio
  pipeline gera (`Loop`, `Oneshot`, `FX_Oneshot_Longo`) são excluídos do
  texto pesquisado — sem isso, checar um caminho de *destino* já migrado
  faria `FX_Oneshot_Longo` (que contém "Oneshot") se auto-confirmar,
  travando qualquer re-checagem. É por isso que `fix_classification_v2.py`
  passa só o nome do arquivo (`clean_stem`), nunca o caminho de destino
  inteiro, pro pré-check — nesse caso o check de "loop" (que agora também
  olharia pasta) fica de fato restrito ao nome, porque não sobram pastas
  de origem reais depois da migração, só as de classificação (excluídas).
- Não inventamos lista de mais palavras-chave (`"hit"`, `"riser"` etc.) sem
  evidência — nenhum caso concreto de falha exigiu isso ainda.

### Passo 2 — fallback por análise de áudio (`_classify_sound_type`)

Só roda quando o Passo 1 não achou evidência textual. Critério atual, por
comportamento (substituiu onset-regularity + chroma-similaridade, ambos
testados contra a biblioteca real e achados não confiáveis — onset-
regularidade excluía loops reais com swing/síncope; chroma-similaridade
media igual para impactos one-shot e loops de verdade):

- Conta picos locais no envelope de energia RMS suavizado — um loop de
  verdade tem vários ciclos alto/baixo, um one-shot (mesmo longo) tem uma
  única tendência dominante.
- **Loop** — picos suficientes (`min_energy_peaks_for_loop`/`_fx`,
  3 para tipo Fx por causa do caso "banco de one-shots concatenados", 2 pro
  resto) espalhados até pelo menos metade do arquivo
  (`min_last_peak_fraction_for_loop`), e duração ≥ `min_loop_duration_seconds`
  (1.5s — abaixo disso é fisicamente impossível ser um loop musical nesse
  BPM range).
- **Oneshot** / **FX_Oneshot_Longo** — sem repetição rítmica, diferenciados
  só por duração (`short_oneshot_max_duration_seconds`).
- Limitação conhecida, não resolvida: um "banco" de FX diferentes
  concatenados num wav longo (ex. 2 risers distintos em 1 arquivo) ainda
  pode passar como Loop — nenhum sinal de áudio testado até agora
  (regularidade de onset, chroma, autocorrelação) distingue isso de um loop
  real de forma limpa.

FX não tem tempo, então é organizado por pasta de duração
(`0-3s/3-8s/8-20s/20s+`) em vez de faixa de BPM.

## Supressão de BPM/Key por classificação (`_apply_suppression_rules`)

Passe final, sobrepõe qualquer fonte (nome de arquivo, tag ID3, análise):

- **BPM** só é mantido quando `classificação == Loop`.
- **Key** é anulada só quando `tipo == Drums E classificação == Oneshot`.
- Nome de arquivo omite o colchete `[bpm]`/`[key]` inteiro quando nulo.
- Confiança se adapta aos campos que realmente se aplicam.

## Brilho espectral (`_classify_brightness`, campo `brightness`)

Escuro / Medio / Claro / Full_Spectro — energia distribuída entre 3 faixas
de frequência (`config/genre_mapping.json` → `brightness_bands`). Sempre
calculado (timbre existe em qualquer som).

## Bugs encontrados e corrigidos — rodada 1 (implementação inicial)

- **`librosa.beat.tempo(onset_env=...)`** — kwarg renomeado + função
  realocada na v0.11. `except` genérico engolia o erro — cobertura de BPM
  foi de 25% → 96.5% depois de trocar pra
  `librosa.feature.tempo(onset_envelope=...)`.
- **`_extract_type_from_name`** lia o caminho completo em vez do nome do
  arquivo — pasta pai contaminava a detecção de tipo. Corrigido pra ler só
  o basename.

## Bugs encontrados e corrigidos — rodada 2 (testes reais pós-Ciclo-1)

Achados testando de verdade contra a biblioteca real (dry-run + cópia
real + simulação com dados reais), não só lendo código. Cada um foi
quantificado antes de corrigir.

### "Drums" engolindo Lead/Bass/Synth/Arp/Pad

`type_keywords.Drums` incluía `"loop"` e `"break"` — quase todo arquivo de
loop tem "Loop" no nome, então `_extract_type_from_name` (que retorna no
primeiro match, testando Drums primeiro) classificava `PML_MTA2_Lead_Loop_026`
como Drums só por causa do "Loop". **47,8% da biblioteca inteira (5.614 de
11.742 arquivos do Ciclo 1) estava em Drums**; pelo menos 1.933 sem
nenhuma palavra real de bateria no nome. Corrigido: removido `loop`/`break`
(duplicado na lista original, aliás), adicionado `perc` (abreviação real
usada em 727 arquivos, não reconhecida antes — só "percussion" completo
estava na lista). Resultado simulado: Drums cai pra 36,8%, Leads mais que
dobra (623→1.342), Bass e Pads sobem proporcionalmente.

### BPM fabricado de número de faixa/catálogo

`bpm_patterns[0]` tinha um branch de fallback `\D|$` — "número de 2-3
dígitos seguido de qualquer coisa que não seja dígito, ou fim de string".
Isso casa com **qualquer** número nesse range, não só BPM. Medido: dos
3.534 "BPMs" extraídos do nome de arquivo, **2.666 (75%) não tinham a
palavra "bpm" em lugar nenhum do nome** — eram número de faixa
(`082(a) Zenhiser OTT1.wav` → "BPM 82"). Pior: como o BPM do nome de
arquivo tem prioridade sobre a estimativa por análise de áudio
(`if bpm_from_name and not result['bpm']`), um valor fabricado **impedia**
a estimativa correta via librosa de rodar. Corrigido: removido o fallback
genérico, o padrão agora exige a palavra "bpm" de verdade; bracket/underscore
viram fallback secundário, só usados quando não há "bpm" no nome.

### Tonalidade fabricada de letra solta

`key_patterns[2]` era `(\w#?m?)(?:\s|_|$)` — qualquer letra sozinha antes
de espaço/underscore/fim, sem exigir contexto de tonalidade nenhum. Amostra
real (25 casos): **100% eram lixo** — `ALPHA WET [2018...].wav` → "A" (letra
de "ALPHA"), `BD Click.wav` → "D" (letra de "BD"). Removido inteiramente;
os padrões de bracket (`[Am]`) e underscore (`_Am_`) validados como
confiáveis (30/30 corretos numa amostra aleatória separada) continuam.

### Convenção `Cmin`/`D#Maj` nunca reconhecida

Nome completo de nota + modo maior/menor (não abreviado tipo `[Am]`).
Nenhum padrão de regex existente conseguia casar (capturam no máximo 3
caracteres, "Cmin" tem 4+). Confirmado em **932 arquivos de áudio e 273 de
MIDI/presets** via varredura direta na biblioteca. Implementado como passo
dedicado (não um regex genérico — precisa transformar "min"→sufixo "m",
"maj"→sem sufixo) checado antes dos padrões genéricos, já que é ainda mais
explícito que um `[Am]` entre colchetes.

### BPM/key lendo o caminho completo, não o nome do arquivo

Mesma classe de bug já corrigida em `_extract_type_from_name` (rodada 1),
nunca aplicada a `_extract_bpm_from_name`/`_extract_key_from_name` até
agora — ficou sinalizado como "risco teórico" por uma sessão inteira.
Quantificado contra os 12.713 arquivos reais: **544 arquivos tinham BPM
diferente** comparando extração por caminho completo vs. só nome (alguns
casos o caminho completo *perdia* um BPM válido do nome porque um match
espúrio mais cedo no caminho "gastava" a tentativa daquele padrão sem
tentar de novo mais adiante na string); **262 arquivos tinham key
diferente** (pasta como `5 KIT_122_F_QWANTI` vazando "F" pra todo arquivo
dentro, incluindo shakers sem afinação nenhuma). Corrigido pra
`os.path.basename(filepath)`, mesmo padrão do tipo.

### Tags de gênero ID3 sem normalização

`existing_metadata['genre']` (de tag `TCON`/`GENRE`) era usado **verbatim**
— nunca passava pela lista curada `genre_keywords` nem pelo dict
`genre_mappings` (que existia especificamente pra isso, mas nunca foi
chamado em código nenhum — mesma classe de "config morto" do
`duration_ranges_fx`, ver seção de paralelismo). Resultado real: pastas
soltas tipo `Melodic House & Techno`, `Organic House` no destino, ao lado
de `Techno`/`House` já curados — a mesma música ficando espalhada em nomes
de pasta diferentes dependendo de qual arquivo você olhasse. Corrigido:
tag ID3 agora passa pela mesma busca por palavra-chave do nome de arquivo
antes de virar o gênero final; se não bater com nenhum gênero conhecido,
cai pro nome de arquivo em vez de confiar num valor solto.

### Taxonomia de subgênero achatada — a correção virou uma varredura completa

Ao corrigir o problema de ID3 acima, o usuário apontou que "Melodic House"
e "Melodic Techno" são subgêneros **diferentes** de House/Techno genérico
— não deveriam ser normalizados pra dentro do gênero pai. Isso levou a uma
varredura sistemática nas 3 pastas fonte (nomes de pasta, não conteúdo de
arquivo — mais rápido e genre já é extraído do caminho completo mesmo)
procurando por outros subgêneros sendo engolidos da mesma forma. Achados,
todos confirmados como packs reais (filtrando falsos positivos tipo
"DISCOVER" contendo "disco" como substring):

`Deep House`, `Deep Techno`, `Minimal House`, `Minimal Techno`,
`Progressive House`, `Progressive Techno`, `Organic House`, `Tech House`,
`Slap House`, `Afro House`, `Dub Techno`, `Big Room`, `Reggaeton`, `Funk`,
`Afrobeat`, `Nu Disco`, `Disco`, `Synthwave`, `LoFi`, `Hardstyle`,
`Garage`, `Tribal`.

**Causa raiz de por que isso não funcionava mesmo com `genre_mappings`
existindo**: a função de busca (`_extract_genre_from_path`) itera
`genre_keywords` na ordem do dict e retorna no primeiro match — como
`House` sempre foi checado antes de qualquer entrada mais específica, e a
própria lista de `House` incluía `"deep house"`, `"tech house"` etc. como
palavras-chave suas, uma frase composta como "Deep House" batia em `House`
primeiro, nunca chegava a ser considerada `Deep`. `genre_mappings` tentava
expressar a intenção certa (mapear "deep house" → "Deep") mas nunca foi
de fato chamado em lugar nenhum do código — duas fontes de verdade
divergentes, nenhuma efetivamente aplicada.

**Solução**: uma taxonomia só, ordenada mais-específico-primeiro no dict
(`Melodic House` antes de `House`, `Deep Techno` antes de `Techno`, etc.).
`genre_mappings` removido — resolvia o mesmo problema de um jeito que
nunca foi ligado ao código, mantê-lo seria deixar config morto pra trás de
novo (mesma lição do `duration_ranges_fx`).

### Colisão de nome descartando arquivo silenciosamente

`FileOrganizer.copy_file()` sempre fez só `if dest_path.exists(): skip` —
sem comparar conteúdo. Confirmado com hash MD5 real: dentro de só
`-ELETRONIC MUSIC-`, **967 nomes de arquivo se repetem** (2.540 arquivos
envolvidos); testando uma amostra, `Perc.wav` tem **5 conteúdos diferentes
em 9 cópias** — não é duplicata de verdade, são arquivos diferentes que
por acaso têm o mesmo nome em packs diferentes. **Flagrado ao vivo**: um
piloto real de 250 arquivos teve 3 colisões, descartadas silenciosamente
antes da correção. Corrigido com o mesmo padrão já implementado e testado
no pipeline de MIDI+Presets: hash MD5 computado na fase de validação,
carregado até a fase de migração; se o destino já existe e o hash bate, é
duplicata real (pula, log de "já existe"); se o hash difere, desambiguado
com um sufixo curto do hash em vez de sobrescrever ou descartar.

**Lição de padrão**: a mesma classe de bug (checar só "existe" sem checar
"é a mesma coisa") apareceu duas vezes neste projeto — uma vez identificada
e corrigida no pipeline novo por decisão explícita durante o design, outra
vez só descoberta no pipeline antigo testando de verdade e flagrando o
descarte acontecendo. Vale desconfiar de qualquer "skip se já existe" que
não compara conteúdo.

## Diagnóstico de arquivos rejeitados (`diagnose_rejected.py`)

100% das rejeições são corrupção real e irrecuperável — **100% rastreado a
5 pastas específicas da marca "Exotic Refreshment"** (95.5% de corrupção
só nelas). Resto da pasta está limpo.

## Performance: paralelismo com auto-calibração (`--parallel-workers`)

**Auto-calibração** (`modules/benchmark.py`, compartilhado pelos dois
pipelines). Antes de cada rodada real, testa números de workers candidatos
(`{1, cpu//2, cpu-1, cpu}`) contra uma amostra real dos arquivos desta
pasta, neste disco, agora — usa o mais rápido. Roda pra validação (threads,
I/O-bound) e análise (processos, CPU-bound) de forma independente.

**Dois cuidados metodológicos**: amostra igual por candidato (evita que o
candidato maior amortize seu próprio custo de startup melhor), arquivos
diferentes por candidato (evita viés de cache do SO nos candidatos
testados depois).

**Achado que só a calibração real revela**: calibrando a fase de validação
pela etapa de hash MD5, **1 thread às vezes venceu 8** neste HD específico
— leitura concorrente pode ser pior que sequencial num disco mecânico.
Motivo exato de calibrar em vez de fixar um número.

---

# Pipeline de MIDI + Presets (`migrate_midi_presets.py`)

## Por que um script separado, não um `--mode` no pipeline de áudio

`migrate_samples.py` já rodou de verdade (Ciclo 1) — qualquer edição nele,
por menor que seja, mexe em código já validado. A taxonomia também é
completamente diferente (sem genre/type/BPM de áudio), então bifurcar
dentro de `SampleMigrator` bagunçaria duas responsabilidades não
relacionadas numa classe só. Reaproveita só o que é genuinamente genérico
e somente-leitura: `modules/benchmark.py` (sem nada de áudio) e
`config/genre_mapping.json` (gêneros e padrões de regex de BPM/key —
lido, nunca escrito).

## MIDI: tempo e tonalidade com fallback por nome de arquivo

**Tempo**: **prioridade invertida em 2026-07-25, a pedido explícito do
usuário** — nome do arquivo é checado primeiro, meta-evento Set Tempo só
preenche quando o nome não tem "bpm" literal nenhum. Antes era o oposto
(meta-evento sempre vencia por ser um fato técnico exato do arquivo, não
uma tag solta) — o usuário foi avisado dessa diferença explicitamente
(meta-evento MIDI não é "metadado" no sentido de tag ID3 descurada, é o
tempo real de reprodução gravado na estrutura do arquivo) e optou por
aplicar a mesma regra de prioridade mesmo assim, pela mesma lógica
"nome/pasta é majoritário" usada em todo o resto do projeto. `has_tempo_meta`
mantém o significado original (o valor em `tempo_bpm` veio do meta-evento
especificamente, não só "existe um meta-evento no arquivo") porque
`midi_preset_reporter.py` e `midi_preset_organizer.py` dependem desse
contrato exato — por isso o meta-evento só é sequer consultado quando o
nome não respondeu nada, em vez de rodar sempre e só perder a prioridade.

**93,5% dos arquivos `.mid` reais desta biblioteca não têm meta-evento Set
Tempo nenhum** (a maioria dos DAWs não exporta). Desses, ~28% têm o tempo
escrito no próprio nome (`PML_Telekinesis_127bpm Amin_Pad.mid`) — antes
descartado por completo. Extração reaproveita os mesmos padrões corrigidos
de BPM do pipeline de áudio, mas **mais conservadora**: só aceita o padrão
que exige a palavra "bpm" literal, não o fallback de bracket/underscore que
é confiável pra áudio mas *não* pra MIDI — um pack real
(`PML_MIDIQ_Stab_Melody_56_Amin_EDM.mid`) tem numeração sequencial de
faixa no mesmo formato `_NN_` que o padrão de áudio usa pra tempo, e
fabricou "56 bpm" a partir do índice antes dessa restrição.

**Tonalidade**: prioridade pro nome do arquivo sobre a heurística de notas
(correlação de histograma de pitch-class contra perfis Krumhansl-Kessler).
Achado real de discordância: um arquivo chamado `...Fmin.mid` teve a
heurística "adivinhando" C# — o nome é a intenção declarada do produtor,
mais confiável que uma correlação estatística. A tag `~` no nome final só
aparece quando a tonalidade vem mesmo da heurística (`key_note_analysis`
no campo `source`); vinda do nome ou de meta-evento, sem `~`.

## Presets: dois tiers, sem inventar parser pra formato sem documentação

- **Tier A** (`.serumpreset`, `.vital`, `.sfz`) — parse real: JSON primeiro,
  texto puro depois, fallback gracioso pra nome-de-arquivo-só se nada
  parsear (nunca marca como inválido). **Categoria: prioridade invertida em
  2026-07-25** (mesmo pedido do usuário aplicado ao tempo do MIDI acima) —
  nome do arquivo (`BS`/`PD`/`SQ`...) é checado primeiro, o campo `category`
  parseado do JSON só preenche quando o nome não resolveu nada. `preset_name`
  não foi reordenado — não é um campo de categorização, não tem um
  concorrente textual equivalente no nome genérico do arquivo pra disputar
  prioridade.
- **Tier B** (`.fxp`, `.nki`, `.nmsv`, `.repatch`, `.spf`/`.spf2`, `.h2p`,
  `.sxt`/`.flx`/`.kit`, `.exs`) — binários proprietários sem doc estável.
  Copia + indexa por nome/extensão/família de plugin inferida, sem
  tentar decodificar o conteúdo. `.exs` (EXS24) foi rebaixado pra este
  tier apesar de ter alguma doc parcial de terceiros — formato
  descontinuado, volume baixo (435 arquivos), não compensa o esforço.

## Categoria por abreviação de nome de arquivo

Empresas de sample pack abreviam categoria de som no nome: `PD`=Pad,
`SQ`=Sequence, `BS`=Bass, etc. Pesquisado contra convenções reais (preset
naming do Access Virus, guias de produtor) **e** validado contra nomes
de arquivo reais desta biblioteca antes de implementar — ex: confirmado
que `BA` também significa Bass (`Banshee - BA - Simple Sub.fxp`), que
`STB` era ambíguo demais pra mapear com confiança (aparecia tanto em
presets de bass quanto de pad no mesmo pack) e foi descartado.

Matching por **token inteiro** (`modules/category_matcher.py`), não
substring — abreviações de 2-3 letras precisam disso, diferente de
palavras de gênero completas: "BS" como substring bateria dentro de
qualquer palavra que contivesse essas duas letras seguidas.

Resultado numa amostra real de 150 arquivos: cobertura foi de ~0%
(quase tudo caindo em "Uncategorized") pra 87% categorizado
corretamente. O resto ficou em "Uncategorized" de propósito — nomes
genuinamente genéricos (`Backing Loop`, `White Noise`) sem sinal de
categoria nenhum, sem inventar dado que não está lá.

## Colisão de nome — decisão do usuário

Nomes de preset se repetem muito entre packs (`Init.fxp`, `Default.vital`).
Pergunta feita antes de implementar: aceitar o risco (mesmo comportamento
simples do pipeline de áudio na época) ou desambiguar por hash. Decisão:
**desambiguar** — se o destino calculado já existe mas o hash MD5 do
conteúdo é diferente, acrescenta um sufixo curto do hash ao nome em vez
de pular. Só pula de verdade quando o hash bate (idempotência real, mesmo
arquivo re-processado). Esse mesmo padrão foi depois portado pro pipeline
de áudio quando o problema análogo apareceu lá também (ver seção de bugs
acima).

## `.ncw`/`.rx2` — decisão do usuário

~8.700 arquivos de áudio real (Native Instruments compressed WAV,
Propellerhead REX2/Recycle) em formato proprietário que nem `librosa` nem
`mutagen` abrem, e que não tinham decoder disponível sem biblioteca
especializada adicional. Sinalizado como achado durante teste de
cobertura de extensão. **Decisão: fora de escopo, não vamos usar.**

---

## Gênero "Outros" → nome do pack original + pesquisa na internet (2026-07-23)

**Achado**: um arquivo (`SO_SE_88_drum_loop_nolater.wav`, pack "Sensaciones
Latin RnB") caiu em `Outros` porque nenhuma keyword de gênero cadastrada
batia no caminho. Varredura completa das 3 pastas fonte (166.808 arquivos
de áudio) mostrou que **56,6% de toda a biblioteca** caía em `Outros` —
não era um caso isolado, era a maioria dos arquivos sem gênero eletrônico
explícito no nome (packs de Pop, Latin, R&B, Soul, percussão brasileira,
K-Pop, etc., nenhum desses gêneros estava na lista original de 36).

**Correção em duas camadas**:
1. **13 gêneros novos cadastrados** em `genre_keywords`, cada um validado
   contando ocorrências reais na biblioteca antes de adicionar (padrão já
   estabelecido nesta sessão): Drill, Bachata, Merengue, Salsa, Latin, RnB,
   Soul, Samba, Forro, Axe, K-Pop, Pop, Reggae. Resultado real: `Outros`
   caiu de 56,6% para 43,1% (94.369 → 71.822 arquivos), com 22.547
   arquivos resgatados — destaque pra Pop (13.220) e Soul (2.810).
2. **`Outros` nunca mais é o destino final quando existe um nome real
   disponível.** Quando nenhuma keyword bate, `_fallback_genre_from_pack()`
   (`audio_analyzer.py`) usa o nome da pasta-pack de origem (ex. "Maschine
   Samples", "Bachata Pura") em vez do bucket genérico — usuário foi
   direto: "Nome OUTROS nao me ajuda em nada". `Outros` literal só
   acontece pra arquivo solto direto na raiz da pasta fonte (2 casos reais
   em 166.808 arquivos).
   - Pastas-guarda-chuva descobertas por inspeção real (SPLICE, SLATE
     SAMPLES, AlgonautContent/Packs Installed) são puladas — são
     agregadores que empacotam vários packs distintos um nível abaixo, não
     packs em si; sem esse tratamento, ~38 mil arquivos cairiam todos sob
     o nome genérico "SPLICE".

**Pesquisa na internet pra nomes de artista/label** (pedido explícito do
usuário: "buscar pelo nome da empresa e o nome do pack pra saber de qual
gênero se trata"). Quando o nome do pack é um artista/produtor em vez de
uma palavra de estilo (ex. "Deadmau5", "KSHMR"), keyword nenhuma resolve —
o gênero só existe pesquisando quem é o artista. 14 packs pesquisados e
mapeados em `pack_genre_overrides` (chave = nome exato da pasta, checado
antes do fallback puro): Deadmau5→Progressive House, KSHMR (3 packs)→Big
Room, Chrome Sparks→Chillwave (gênero novo), Com Truise→Synthwave,
Getter→Dubstep, KRANE/Fabian Mazur/Ekali/Tropkillaz→Trap, Just
Blaze→HipHop, Del B→Afrobeat. Validado: 22.325 arquivos migraram de nome
de pasta pra gênero real (Big Room 10.747, Progressive House 2.926, etc).

**Ferramenta de pré-voo**: `audit_genre_coverage.py`, criada como passo
obrigatório antes de qualquer ciclo novo (documentado em PLAN.md) —
varredura rápida por caminho/keyword (sem carregar áudio), reporta em 3
níveis: gênero por keyword, gênero por pesquisa já resolvida, e pastas
ainda sem gênero conhecido (candidatas a próxima pesquisa).

**Paridade no pipeline de MIDI+Presets**: o mesmo bug (`'Outros'` como
default) existia em `midi_preset_organizer.py`/`midi_analyzer.py`/
`preset_analyzer.py` — mesmo padrão já aprovado no áudio, aplicado direto
sem re-perguntar. A lógica de fallback compartilhada (`GENERIC_PACK_
CONTAINERS`, `resolve_pack_name`, `fallback_genre_from_pack`) foi colocada
em `genre_matcher.py` (módulo já neutro/compartilhado, sem dependência de
`audio_analyzer.py`) em vez de duplicar em `audio_analyzer.py` de novo —
o pipeline de áudio manteve sua própria cópia já testada, intocada,
respeitando a decisão de arquitetura de manter os dois pipelines isolados.

**Validação end-to-end**: destinos limpos, teste real (não dry-run) de 500
arquivos por pipeline na pasta `-ELETRONIC MUSIC-`. Áudio: 500/500
válidos, 0 duplicados, 500/500 migrados, zero `Outros` na distribuição de
gênero (21 gêneros reais, soma bate 500). MIDI+Presets: 500/500 válidos,
500/500 migrados (223 MIDI + 277 presets), zero `Outros`. Hash MD5 de 8
arquivos aleatórios (original vs. cópia): 8/8 idênticos. Zero erros/
tracebacks em nenhuma das fases dos dois pipelines.

## Notas de colaboração

- Revisão de relatório piloto → brief estruturado com mudanças numeradas →
  implementação exata do que foi pedido → validação → aprovação antes de
  escalar pro ciclo completo.
- Achados fora do escopo aprovado são sinalizados mas não corrigidos até
  aprovação explícita — exceto quando o mesmo padrão de bug já foi
  aprovado e corrigido em um pipeline, e reaparece confirmado por
  evidência real no outro (aplicado direto, não re-perguntado).
- Toda correção de regex/keyword nesta sessão foi validada contra dados
  reais da biblioteca antes de implementar (contagem, amostra aleatória,
  não só teoria) — e re-validada depois de implementar.

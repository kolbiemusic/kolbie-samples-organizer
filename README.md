# KOLBIE SAMPLES - Organizador de Áudio, MIDI e Presets

Duas ferramentas complementares para organizar e catalogar uma biblioteca
grande de produção musical, com extração automática de metadados:
`migrate_samples.py` para arquivos de áudio, `migrate_midi_presets.py`
para MIDI e presets de synth/DAW. Cada uma escreve numa árvore de destino
separada — nunca uma dentro da outra.

## 📋 Características

**Pipeline de áudio** (`migrate_samples.py`):
- ✅ Análise automática de BPM e tonalidade (meta-evento/tag → nome de arquivo → análise de áudio)
- ✅ Detecção de Loop vs One-shot vs FX por comportamento, não duração
- ✅ Classificação inteligente de gênero e subgênero (Melodic House ≠ House, Deep Techno ≠ Techno...)
- ✅ Brilho espectral (Escuro/Medio/Claro/Full_Spectro)
- ✅ Remoção de duplicatas + desambiguação de colisão de nome, ambos por hash MD5
- ✅ Validação de integridade de áudio

**Pipeline de MIDI + Presets** (`migrate_midi_presets.py`):
- ✅ Tempo/compasso exato via meta-evento, com fallback por nome de arquivo quando ausente
- ✅ Tonalidade: nome de arquivo (intenção explícita) > heurística por notas (estatística)
- ✅ Presets: parse real de conteúdo quando o formato permite (Serum/Vital/sfz), indexação por nome nos formatos binários sem documentação
- ✅ Categoria por abreviação de nome (`PD`→Pad, `SQ`→Sequence, `BS`→Bass...)

**Compartilhado pelos dois**:
- ✅ Paralelismo com auto-calibração (sem número fixo hardcoded)
- ✅ Geração de índices CSV, JSON e relatórios HTML
- ✅ Execução iterativa (1 pasta fonte por vez), resume automático se parar

## 🚀 Quick Start

### 1. Setup (uma única vez)

```bash
pip install -r requirements.txt
```

### 2. Teste Piloto (amostra pequena, dry-run)

```bash
# Áudio
python3 migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --dry-run --sample-size 150 --verbose

# MIDI + Presets
python3 migrate_midi_presets.py \
  --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" \
  --dry-run --sample-size 150 --verbose
```

### 3. CICLO 1: `-ELETRONIC MUSIC-`

```bash
# Áudio — simular primeiro, depois rodar de verdade
python3 migrate_samples.py --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" --dry-run --verbose
python3 migrate_samples.py --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" --verbose

# MIDI + Presets — mesma lógica, destino tem default próprio (não precisa passar --destination)
python3 migrate_midi_presets.py --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" --dry-run --verbose
python3 migrate_midi_presets.py --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" --verbose
```

**Validação pós-ciclo** (nas duas árvores):
- [ ] Revisar 20-30 arquivos copiados
- [ ] Verificar estrutura de gêneros/categorias
- [ ] Validar nomes com BPM/tonalidade
- [ ] Ver relatório HTML em `_DOCUMENTATION/Migration_Report.html`

### 4. CICLO 2 e 3: `SAMPLES ABLETON`, `NEW SAMPLES N PRESETS`

Mesmos comandos, trocando `--source-dir`. Ver [PLAN.md](./PLAN.md) para o
roteiro completo.

## ⚙️ Paralelismo automático (`--parallel-workers`)

Igual nos dois pipelines. **Por padrão o script se auto-calibra.** Antes de
cada rodada real, testa números de workers candidatos — baseados na
contagem de núcleos da máquina — contra os arquivos reais que serão
processados nesta pasta, neste disco, agora:

```bash
# Auto (padrão)
python3 migrate_samples.py --source-dir "..." --destination "..."

# Forçar um número específico e pular a calibração
python3 migrate_samples.py --source-dir "..." --destination "..." --parallel-workers 4

# Sequencial puro
python3 migrate_samples.py --source-dir "..." --destination "..." --parallel-workers 1
```

Por quê auto em vez de fixo: ver [DECISIONS.md](./DECISIONS.md#performance-paralelismo-com-auto-calibração---parallel-workers).

## 🎛️ Flag específica do pipeline de MIDI + Presets

```bash
# Rodar só MIDI ou só presets primeiro (perfis de custo diferentes)
python3 migrate_midi_presets.py --source-dir "..." --include midi
python3 migrate_midi_presets.py --source-dir "..." --include presets
python3 migrate_midi_presets.py --source-dir "..." --include all   # default
```

## 📁 Estrutura de Destino

### Pipeline de áudio — `KOLBIE SAMPLES/`

```
/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES/
├── House/
│   ├── Drums/
│   │   ├── Loops/{faixa_bpm}/
│   │   ├── Oneshots/{faixa_bpm}/
│   │   └── FX_Oneshot_Longo/{faixa_duração}/
│   ├── Bass/  Pads/  Leads/  Vox/  Fx/
├── Melodic House/  Melodic Techno/  Deep House/  Deep Techno/
├── Minimal House/  Minimal Techno/  Progressive House/  Progressive Techno/
├── Organic House/  Tech House/  Slap House/  Afro House/  Dub Techno/  Big Room/
├── Techno/  Deep/  Minimal/  Progressive/  Trance/  DnB/  Dubstep/  Trap/
├── HipHop/  Reggaeton/  Reggae/  Funk/  Afrobeat/  Nu Disco/  Disco/  Synthwave/
├── LoFi/  Hardstyle/  Garage/  Tribal/  Ambient/  Cinematic/  Experimental/
├── Drill/  Bachata/  Merengue/  Salsa/  Latin/  RnB/  Soul/  Samba/  Forro/
├── Axe/  K-Pop/  Pop/  Chillwave/
├── {Nome do pack original}/   ← fallback, quando nenhum gênero acima bate (ver abaixo)
├── _METADATA/all_files.json
├── _DOCUMENTATION/Migration_Report.html
└── KOLBIE_SAMPLES_INDEX.csv
```

Gêneros/subgêneros são data-driven em `config/genre_mapping.json` — ver
seção de configuração abaixo. A lista acima é a taxonomia atual, não uma
lista fechada.

**Não existe mais pasta genérica "Outros".** Quando nenhuma keyword de
gênero bate no caminho do arquivo, o pipeline usa o nome real da
pasta-pack de origem (ex. `Maschine Samples/`, `Bachata Pura/`) — ou, se
esse pack já foi pesquisado e mapeado (nome de artista/label que não
descreve o estilo, ex. "Deadmau5"), o gênero real resolvido em
`pack_genre_overrides`. `Outros` só aparece pro caso raro de um arquivo
solto direto na raiz da pasta fonte, sem nenhuma pasta acima. Ver
[DECISIONS.md](./DECISIONS.md) para o rationale completo e
`audit_genre_coverage.py` abaixo para o passo de verificação.

### Pipeline de MIDI + Presets — `KOLBIE PRESETS:MIDI/`

```
/Volumes/SAMPLES & LOOPS/KOLBIE PRESETS:MIDI/
├── MIDI/
│   └── {Gênero}/{Categoria}/{faixa_tempo}/{compasso}/
│       └── nome_original [120 bpm] [Cmaj~] [4bars].mid
├── Presets/
│   └── {Gênero}/{Categoria}/{FamíliaPlugin}/
│       └── nome_original.fxp
├── _METADATA/all_files.json
├── _DOCUMENTATION/Migration_Report.html
└── KOLBIE_MIDI_PRESETS_INDEX.csv
```

## 🔀 Taxonomia de Classificação — Áudio (Loop / Oneshot / FX)

A classificação **não usa duração como critério principal**. O eixo real é
**loopabilidade e comportamento rítmico** (`audio_analyzer.py::_classify_sound_type`):

| Categoria | Critério real | Exemplo |
|---|---|---|
| **Loop** | Onsets regulares (groove) + ponto de loop consistente | Loop de bateria, loop melódico |
| **Oneshot** | Evento único curto, decai a silêncio, 0-2 onsets | Kick, snare, clap |
| **FX_Oneshot_Longo** | Evento único mas longo, sem repetição rítmica interna | Sweep, riser, impacto, atmosfera |

Ajustável em `config/genre_mapping.json` → `classification_thresholds`.

## 🎹 Categoria — MIDI + Presets (`PD`/`SQ`/`BS`...)

Extraída do **nome do arquivo por token inteiro**, não substring — evita
que "BS" bata dentro de qualquer palavra que contenha essas letras.
16 categorias (Bass, Lead, Pad, Pluck, Sequence, Arp, Keys, Chord, Stab,
Synth, Fx, Vocal, Brass, Strings, Organ, Drums), cada uma com abreviação +
forma completa. Ajustável em `config/preset_mapping.json` → `category_keywords`.

## 📊 Outputs (iguais nos dois pipelines)

- **CSV Index** — índice completo (nome original, caminho novo, metadados extraídos)
- **JSON Metadata** (`_METADATA/all_files.json`) — todos os metadados, incluindo proveniência (`source`) de cada campo — pra saber se um valor veio de meta-evento exato, nome de arquivo, ou heurística
- **HTML Report** (`_DOCUMENTATION/Migration_Report.html`) — distribuição por gênero/tipo/categoria, estatísticas gerais

## 🔧 Configuração

### Adicionar gêneros (compartilhado pelos dois pipelines)

Editar `config/genre_mapping.json` → `genre_keywords`. **Ordem importa**:
subgêneros compostos devem vir antes do gênero pai genérico, senão o pai
"engole" o composto:

```json
{
  "genre_keywords": {
    "Deep House": ["deep house"],
    "House": ["house", "acid house"],
    "Seu_Subgenero": ["keyword1"]
  }
}
```

### Ajustar tipo de instrumento (só pipeline de áudio)

```json
{
  "type_keywords": {
    "Drums": ["drum", "kick", "snare", "perc"],
    "Seu_Tipo": ["keyword1"]
  }
}
```

### Adicionar plugin/categoria de preset (só pipeline de MIDI + Presets)

Editar `config/preset_mapping.json` → `extension_plugin_map` (extensão →
família de plugin) e `category_keywords` (token de nome → categoria).

### Gênero de pack de artista/label (`pack_genre_overrides`)

Quando o nome da pasta-pack é um artista/produtor/label em vez de uma
palavra de estilo (ex. `Deadmau5`, `KSHMR`), nenhuma keyword resolve —
o gênero só existe pesquisando quem é o artista. Adicionar em
`config/genre_mapping.json` → `pack_genre_overrides`, chave = nome exato
da pasta de origem:

```json
{
  "pack_genre_overrides": {
    "Deadmau5": "Progressive House",
    "Nome Exato Da Pasta Do Pack": "Gênero Real"
  }
}
```

## 🔍 Auditoria pré-voo (`audit_genre_coverage.py`)

**Passo obrigatório antes de rodar um ciclo novo**, ou depois de qualquer
mudança em `genre_mapping.json`. Varre o(s) source dir(s) só por
caminho/keyword (sem carregar áudio — leva segundos, não horas) e reporta
três níveis: gênero por keyword cadastrada, gênero já resolvido por
pesquisa (`pack_genre_overrides`), e pastas ainda sem gênero conhecido
(candidatas à próxima pesquisa).

```bash
python3 audit_genre_coverage.py --source-dir "/caminho/da/pasta/fonte"
python3 audit_genre_coverage.py --all-known-sources   # varre as 3 pastas do projeto
```

## 📝 Convenção de Nomes

**Áudio**: `nome_original [BPM bpm] [Tonalidade] [Brilho].wav` — colchete
inteiro omitido quando o campo não se aplica (nunca um placeholder `[_]`).

**MIDI**: `nome_original [BPM bpm] [Tonalidade] [Nbars].mid` — `~` depois
da tonalidade só quando ela vem de heurística (`[Cmaj~]`); vinda de
meta-evento ou do próprio nome do arquivo, sem `~` (`[Cmaj]`).

## 🔍 Buscando Arquivos

```bash
# Por gênero (áudio)
ls "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES/Melodic Techno/"

# Por categoria (MIDI/presets)
ls "/Volumes/SAMPLES & LOOPS/KOLBIE PRESETS:MIDI/Presets/Techno/Bass/"

# Usando CSV
grep "120 bpm" KOLBIE_SAMPLES_INDEX.csv | grep "House"
```

## ⚠️ Troubleshooting

### Erro: "Module not found"
```bash
pip install -r requirements.txt --upgrade
```

### Formatos não suportados
`.ncw` (Native Instruments) e `.rx2` (Propellerhead REX2) são áudio real
mas em formato proprietário sem decoder disponível — fora de escopo dos
dois pipelines, ficam para trás intencionalmente.

### Parou no meio?
Os dois scripts salvam progresso via cópia idempotente — rode de novo, o
que já foi copiado (mesmo hash) é pulado automaticamente.

## 📞 Support

- Relatórios em `_DOCUMENTATION/Migration_Report.html` de cada árvore
- Índice completo em `_METADATA/all_files.json` de cada árvore
- Rationale técnico completo de cada decisão: [DECISIONS.md](./DECISIONS.md)

## 📄 License

Desenvolvido para KOLBIE SAMPLES Collection

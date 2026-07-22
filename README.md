# KOLBIE SAMPLES - Audio File Organizer

Ferramenta profissional para organizar e catalogar grandes bibliotecas de samples de áudio com extração automática de metadados (BPM, tonalidade, gênero, Loop vs One-shot).

## 📋 Características

- ✅ Análise automática de BPM e tonalidade
- ✅ Detecção de Loop vs One-shot
- ✅ Classificação inteligente de gênero
- ✅ Remoção de duplicatas (MD5)
- ✅ Validação de integridade de áudio
- ✅ Estrutura hierárquica customizável
- ✅ Geração de índices CSV, JSON e relatórios HTML
- ✅ Execução iterativa (1 pasta por vez)
- ✅ Resume automático se parar

## 🚀 Quick Start

### 1. Setup (30 minutos - uma única vez)

```bash
# Instalar dependências
pip install -r requirements.txt

# Criar estrutura de destino
mkdir -p /Volumes/SAMPLES\ \&\ LOOPS/KOLBIE\ SAMPLES/{_METADATA,_DOCUMENTATION}
```

### 2. Teste Piloto (100 arquivos aleatórios)

```bash
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --dry-run \
  --sample-size 100 \
  --verbose
```

### 3. CICLO 1: -ELETRONIC MUSIC- (20.349 arquivos, 176 GB)

```bash
# Simular primeiro
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --dry-run \
  --parallel-workers 4 \
  --verbose

# Se ok, executar para valer
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --parallel-workers 4 \
  --verbose
```

**Tempo estimado**: ~2h (medido no hardware real: M1 Pro 8-core + HD externo USB)

`--parallel-workers 4` paraleliza a fase de análise de áudio (CPU-bound) em
processos separados. **4 é o valor testado e recomendado neste disco** — não
é "quanto mais melhor": testamos 3/4/6 workers e 6 ficou *pior* que 4 porque
o HD externo via USB satura com leituras concorrentes demais (contenção de
disco, não de CPU). Se trocar de disco fonte, vale re-testar com
`--sample-size 300` antes de assumir que 4 continua ótimo.

**Validação pós-ciclo**:
- [ ] Revisar 20-30 arquivos em `/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES/`
- [ ] Verificar estrutura de gêneros
- [ ] Validar nomes com BPM/tonalidade
- [ ] Ver relatório: `KOLBIE_SAMPLES_REPORT_PART1.html`

### 4. CICLO 2: SAMPLES ABLETON (153.977 arquivos, 156 GB)

```bash
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/SAMPLES ABLETON" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --parallel-workers 4 \
  --dry-run

# Se ok
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/SAMPLES ABLETON" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --parallel-workers 4
```

**Tempo estimado**: ~8h. Atenção: com a análise paralelizada, a fase de
**validação** (sequencial, ~1 hora a cada ~31k arquivos neste disco) passa a
dominar o tempo total nesta pasta por ter 153.977 arquivos — candidata a
paralelizar também antes de rodar, se quiser acelerar mais.

### 5. CICLO 3: NEW SAMPLES N PRESETS (41.213 arquivos, 74 GB)

```bash
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/NEW SAMPLES N PRESETS" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --parallel-workers 4
```

**Tempo estimado**: ~2.4h

## 📁 Estrutura de Destino

```
/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES/
├── House/
│   ├── Drums/
│   │   ├── Loops/
│   │   │   ├── 100-110_bpm/
│   │   │   ├── 120-130_bpm/
│   │   │   └── ...
│   │   ├── Oneshots/
│   │   │   ├── unknown_bpm/
│   │   │   └── ...
│   │   └── FX_Oneshot_Longo/
│   │       ├── 0-3s/
│   │       ├── 3-8s/
│   │       ├── 8-20s/
│   │       └── 20s+/
│   ├── Bass/
│   ├── Pads/
│   ├── Leads/
│   ├── Vox/
│   └── Fx/
├── Techno/
├── Deep/
├── Minimal/
├── Trap/
├── DnB/
├── Ambient/
├── Outros/
├── _UNCLASSIFIED/
├── _METADATA/
│   └── all_files.json
├── _DOCUMENTATION/
│   ├── Migration_Report.html
│   ├── README.md
│   └── KOLBIE_SAMPLES_INDEX.csv
```

## 🔀 Taxonomia de Classificação (Loop / Oneshot / FX)

A classificação **não usa duração como critério principal** — um sweep de 8s
não vira "Loop" só por ser mais longo que um kick. O eixo real é
**loopabilidade e comportamento rítmico**, detectado combinando 3 sinais de
análise de áudio (`modules/audio_analyzer.py::_classify_sound_type`):

| Categoria | Critério real | Exemplo |
|---|---|---|
| **Loop** | Onsets regulares (groove) + ponto de loop consistente (início soa como o fim) | Loop de bateria, loop melódico |
| **Oneshot** | Evento único curto, decai a silêncio, 0-2 onsets | Kick, snare, clap |
| **FX_Oneshot_Longo** | Evento único mas longo, sem repetição rítmica interna | Sweep, riser, impacto, atmosfera |

Sinais combinados:
1. **Regularidade de onsets** — coeficiente de variação do intervalo entre onsets; loops têm cadência estável.
2. **Similaridade início/fim (chroma)** — loops são feitos para repetir, então o final "conecta" com o começo.
3. **Formato do envelope de energia** — one-shots (curtos ou longos) decaem a quase-silêncio no final; loops sustentam ou repetem energia.

Como FX longos não têm tempo, são organizados por **faixa de duração**
(`0-3s`, `3-8s`, `8-20s`, `20s+`) em vez de BPM — ver `FileOrganizer.DURATION_RANGES_FX`
em `modules/file_organizer.py`. Sem sinal de áudio (fallback só por metadados/nome),
o sistema nunca assume "Loop" — na dúvida, cai em `Oneshot` (curto) ou `FX_Oneshot_Longo` (longo).

Ajustável em `config/genre_mapping.json` → `classification_thresholds`.

## 📊 Outputs

### CSV Index
`KOLBIE_SAMPLES_INDEX.csv` - Índice completo com:
- Nome original
- Caminho novo
- BPM
- Tonalidade
- Gênero
- Tipo
- Classificação
- Duração

### JSON Metadata
`_METADATA/all_files.json` - Todos os metadados em JSON para:
- Busca programática
- Importação em DAW/software
- Análise estatística

### HTML Report
`_DOCUMENTATION/Migration_Report.html` - Relatório visual com:
- Total de arquivos processados
- Distribuição por gênero
- Distribuição por tipo
- Distribuição por BPM
- Estatísticas gerais

## 🔧 Configuração

### Adicionar Gêneros

Editar `config/genre_mapping.json`:

```json
{
  "genre_keywords": {
    "House": ["house", "deep house", "tech house"],
    "Seu_Genero": ["keyword1", "keyword2"]
  }
}
```

### Ajustar Tipo de Instrumento

```json
{
  "type_keywords": {
    "Drums": ["drum", "kick", "snare"],
    "Seu_Tipo": ["keyword1"]
  }
}
```

## 📝 Convenção de Nomes

Os arquivos copiados seguem o padrão:

```
[ORIGINAL_NAME] [BPM bpm] [TONALIDADE].wav

Exemplos:
- Kick_House_01 [120 bpm] [Am].wav
- Loop_Bass_Deep [110 bpm] [E].wav
- Snare_01 [120 bpm] [_].wav  (tonalidade desconhecida)
```

## 🔍 Buscando Arquivos

### Por BPM
```bash
ls /Volumes/SAMPLES\ \&\ LOOPS/KOLBIE\ SAMPLES/House/Drums/Loops/120-130_bpm/
```

### Por Gênero
```bash
ls /Volumes/SAMPLES\ \&\ LOOPS/KOLBIE\ SAMPLES/Techno/
```

### Por Tipo
```bash
ls /Volumes/SAMPLES\ \&\ LOOPS/KOLBIE\ SAMPLES/House/Bass/
```

### Usando CSV
```bash
grep "120 bpm" KOLBIE_SAMPLES_INDEX.csv | grep "House" | grep "Bass"
```

## ⚠️ Troubleshooting

### Erro: "Module not found"
```bash
pip install -r requirements.txt --upgrade
```

### Erro: "Permission denied"
```bash
# Verificar permissões
ls -la /Volumes/SAMPLES\ \&\ LOOPS/
# Se necessário
sudo chown -R $USER /Volumes/SAMPLES\ \&\ LOOPS/
```

### Parou no meio?
O script salva progresso, apenas execute novamente - retoma de onde parou

## 📈 Próximos Passos Após Migração

1. **Importar em DAW**
   - Abrir índice CSV em seu DAW favorito
   - Criar pack de samples
   - Usar tags BPM para browser

2. **Otimizar Metadados**
   - Revisar arquivos não-classificados em `_UNCLASSIFIED/`
   - Renomear/reorganizar manualmente se necessário

3. **Backup**
   - Copiar estrutura final para backup externo
   - Manter origem como fallback por 30 dias

## 📞 Support

- Logs em `logs/migration.log`
- Relatórios em `_DOCUMENTATION/Migration_Report.html`
- Índice completo em `_METADATA/all_files.json`

## 📄 License

Desenvolvido para KOLBIE SAMPLES Collection

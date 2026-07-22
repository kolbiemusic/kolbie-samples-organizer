# KOLBIE SAMPLES — Plano Completo do Projeto

> Documento de referência único: contexto, estado atual, e roteiro de
> execução. Para o *porquê* de cada decisão técnica, ver [DECISIONS.md](./DECISIONS.md).
> Este documento é o *o quê* e *quando*; DECISIONS.md é o *por quê*.

**Última atualização**: 2026-07-22
**Status geral**: 🟡 Pronto para execução — aguardando aprovação para rodar o Ciclo 1 completo

---

## 1. Objetivo

Migrar e reorganizar **215.539 arquivos de áudio (406 GB)**, hoje espalhados
em 3 pastas fonte com 9.341 subpastas aninhadas sem padrão, para uma
estrutura única, pesquisável e com metadados extraídos automaticamente:

```
/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES/
└── {Gênero}/{Tipo}/{Loop|Oneshot|FX_Oneshot_Longo}/{BPM ou Duração}/
    └── nome_original [bpm] [key] [brilho].wav
```

**Regra inegociável**: arquivos originais são **sempre copiados, nunca
movidos ou apagados**. As 3 pastas fonte permanecem intactas durante e
depois de todo o processo.

---

## 2. Inventário das pastas fonte

| Pasta | Arquivos | Tamanho | Status |
|---|---|---|---|
| `-ELETRONIC MUSIC-` | 20.349 | 176 GB | ✅ Piloto validado, pronto pra rodar |
| `SAMPLES ABLETON` | 153.977 | 156 GB | ⏳ Aguardando Ciclo 1 terminar |
| `NEW SAMPLES N PRESETS` | 41.213 | 74 GB | ⏳ Aguardando Ciclo 2 terminar |

Mapeamento completo (extensões, subpastas) foi feito no início do projeto —
ver histórico de conversa para o relatório de varredura original.

---

## 3. Arquitetura do pipeline

Código em `~/kolbie-samples-migrate/` (também neste repositório):

```
migrate_samples.py       # orquestrador — CLI e as 6 fases
modules/
  audio_analyzer.py       # BPM, key, gênero, tipo, classificação, brilho
  file_validator.py       # integridade de áudio, hash MD5
  file_organizer.py       # caminho de destino, renomeação, cópia
  reporter.py              # CSV, JSON, HTML
  benchmark.py             # auto-calibração de paralelismo
config/genre_mapping.json  # keywords, thresholds, faixas de BPM/duração
diagnose_rejected.py       # diagnóstico standalone de arquivos corrompidos
```

**As 6 fases de cada execução**:
1. **Descoberta** — lista todos os arquivos de áudio na pasta fonte
2. **Calibração automática** — testa números de workers candidatos contra
   arquivos reais desta pasta/disco, escolhe o mais rápido por fase
3. **Validação** — integridade de áudio + detecção de duplicatas (MD5),
   paralela (threads)
4. **Análise** — BPM, tonalidade, gênero, tipo, classificação, brilho
   espectral, paralela (processos)
5. **Migração** — copia pro destino com nome final, na estrutura de pastas
6. **Relatório** — gera CSV, JSON e HTML com o resultado

---

## 4. O que já foi feito

### 4.1 Taxonomia de classificação (Loop / Oneshot / FX)
Reescrita para decidir por **comportamento** (regularidade de onsets,
ponto de loop, formato de envelope de energia) em vez de duração pura —
um sweep de 8s não é mais classificado como "Loop" só por ser longo.

### 4.2 Metadados corretos, sem dados fabricados
- BPM só existe em arquivos `Loop` (tempo não é propriedade de evento único)
- Tonalidade suprimida em percussão sem afinação (`Drums` + `Oneshot`)
- Nome de arquivo omite colchetes vazios em vez de mostrar `[_]`

### 4.3 Brilho espectral (nova dimensão de metadado)
Classificação Escuro / Médio / Claro / Full Spectro por distribuição de
energia em 3 faixas de frequência — tag no nome do arquivo + campo no
CSV/JSON.

### 4.4 Bugs corrigidos
- Estimativa de BPM via `librosa` estava falhando silenciosamente (API
  mudou entre versões) — cobertura foi de 25% → 96.5% após o fix
- Extração de tipo de som lia o caminho completo em vez do nome do
  arquivo, contaminando classificações com texto de pasta pai

### 4.5 Diagnóstico de arquivos corrompidos
100% dos arquivos rejeitados na amostra são corrupção real e
irrecuperável, **100% concentrada em 5 pastas específicas da marca
"Exotic Refreshment"** (95.5% de corrupção só nelas). Resto da pasta
está limpo. Não precisa de etapa de pré-conversão.

### 4.6 Paralelismo com auto-calibração
Validação e análise rodam em paralelo (threads e processos,
respectivamente), com o número de workers **calibrado automaticamente**
contra arquivos reais antes de cada execução — portável pra qualquer
computador ou disco, sem número fixo hardcoded.

### 4.7 Infraestrutura
- Repositório GitHub privado criado e sincronizado
- `gh` CLI instalado e autenticado nesta máquina

---

## 5. Roteiro de execução (o que falta)

### Ciclo 1 — `-ELETRONIC MUSIC-`
```bash
cd ~/kolbie-samples-migrate
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --verbose
```
- **Tempo estimado**: ~2h + calibração (~1min)
- **Status**: pronto, aguardando aprovação final pra rodar de verdade
- **Pós-ciclo**: revisar amostra de arquivos copiados, checar CSV/HTML gerado

### Ciclo 2 — `SAMPLES ABLETON`
```bash
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/SAMPLES ABLETON" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --verbose
```
- **Status**: não iniciado — depende da validação do Ciclo 1
- Maior pasta (153.977 arquivos) — tempo real depende do que a
  calibração automática encontrar nesta rodada

### Ciclo 3 — `NEW SAMPLES N PRESETS`
```bash
python migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/NEW SAMPLES N PRESETS" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --verbose
```
- **Status**: não iniciado — depende da validação do Ciclo 2

### Pós-migração (todos os 3 ciclos concluídos)
- [ ] Revisar estrutura final completa em `/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES/`
- [ ] Conferir amostra de arquivos com hash MD5 (original vs. cópia)
- [ ] Decidir se apaga as pastas fonte originais ou mantém como backup
- [ ] Consolidar os 3 relatórios (CSV/JSON/HTML) em um índice único, se necessário

---

## 6. Riscos conhecidos e mitigação

| Risco | Mitigação |
|---|---|
| Perda de dados | Cópia apenas — original nunca é tocado |
| Disco cheio no destino | ~500GB disponível vs. ~380GB esperado de cópia (após dedup/corrupção) |
| Arquivo corrompido interrompe o processo | Validação isola e reporta, não trava o pipeline |
| Número de workers errado trava/desperdiça CPU | Auto-calibração testa antes de cada rodada real |
| Nome de arquivo muito longo (limite do macOS) | Truncamento automático com `[...]` |

---

## 7. Pendências sinalizadas (não aprovadas ainda)

- `_extract_bpm_from_name`/`_extract_key_from_name` leem o caminho
  completo do arquivo (mesma classe de bug já corrigida na extração de
  tipo) — risco teórico, não confirmado na prática, aguardando decisão
- Nenhuma outra pendência aberta no momento

---

## 8. Links

- Repositório: https://github.com/kolbiemusic/kolbie-samples-organizer
- Rationale técnico completo: [DECISIONS.md](./DECISIONS.md)
- Instruções de uso: [README.md](./README.md)

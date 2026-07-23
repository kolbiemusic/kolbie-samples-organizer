# KOLBIE SAMPLES — Plano Completo do Projeto

> Documento de referência único: contexto, estado atual, e roteiro de
> execução. Para o *porquê* de cada decisão técnica, ver [DECISIONS.md](./DECISIONS.md).
> Este documento é o *o quê* e *quando*; DECISIONS.md é o *por quê*.

**Última atualização**: 2026-07-22
**Status geral**: 🟡 Dois pipelines prontos, corrigidos e testados — aguardando aprovação para rodar os ciclos completos

---

## 1. Objetivo

Migrar e reorganizar **215.539 arquivos** (áudio + MIDI + presets, 406 GB),
hoje espalhados em 3 pastas fonte com 9.341 subpastas aninhadas sem padrão,
para duas árvores de destino separadas, pesquisáveis, com metadados
extraídos automaticamente:

```
/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES/            (pipeline de áudio)
└── {Gênero}/{Tipo}/{Loop|Oneshot|FX_Oneshot_Longo}/{BPM ou Duração}/
    └── nome_original [bpm] [key] [brilho].wav

/Volumes/SAMPLES & LOOPS/KOLBIE PRESETS:MIDI/       (pipeline de MIDI + presets)
├── MIDI/{Gênero}/{Categoria}/{faixa_tempo}/{compasso}/
└── Presets/{Gênero}/{Categoria}/{FamíliaPlugin}/
```

**Regra inegociável**: arquivos originais são **sempre copiados, nunca
movidos ou apagados**. As 3 pastas fonte permanecem intactas durante e
depois de todo o processo.

---

## 2. Inventário das pastas fonte

| Pasta | Arquivos totais | Tamanho | Áudio | MIDI+Presets |
|---|---|---|---|---|
| `-ELETRONIC MUSIC-` | 20.349 | 176 GB | ~12.7k | ~2.6k |
| `SAMPLES ABLETON` | 153.977 | 156 GB | ~120k | ~9.4k |
| `NEW SAMPLES N PRESETS` | 41.213 | 74 GB | ~29k | ~9.2k |

Fora do escopo de ambos os pipelines: `.ncw` (Native Instruments/Kontakt) e
`.rx2` (Propellerhead REX2) — ~8.700 arquivos de áudio real em formato
proprietário sem decoder disponível. **Decisão: não vamos usar, fora de
escopo.**

---

## 3. Arquitetura — dois pipelines isolados

```
~/kolbie-samples-migrate/
├── migrate_samples.py          # pipeline de ÁUDIO — orquestrador, CLI
├── migrate_midi_presets.py     # pipeline de MIDI+PRESETS — orquestrador, CLI
├── modules/
│   ├── audio_analyzer.py       # BPM, key, gênero, tipo, classificação, brilho (áudio)
│   ├── file_validator.py       # integridade de áudio, hash MD5 (compartilhado)
│   ├── file_organizer.py       # caminho/nome/cópia (áudio)
│   ├── reporter.py             # CSV, JSON, HTML (áudio)
│   ├── benchmark.py            # auto-calibração de paralelismo (compartilhado)
│   ├── midi_analyzer.py        # tempo, compasso, key, gênero, categoria (MIDI)
│   ├── preset_analyzer.py      # plugin, categoria, tier A/B (presets)
│   ├── midi_preset_organizer.py # caminho/nome/cópia com desambiguação por hash (MIDI+Presets)
│   ├── midi_preset_reporter.py # CSV, JSON, HTML (MIDI+Presets)
│   ├── genre_matcher.py        # busca de gênero por palavra-chave (compartilhado pelas duas árvores novas)
│   ├── category_matcher.py     # busca de categoria por abreviação de nome (PD/SQ/BS...)
│   └── logging_setup.py        # setup de log do pipeline novo (com --verbose corrigido)
├── config/
│   ├── genre_mapping.json      # gêneros, tipos, padrões de BPM/key (pipeline de áudio, lido também pelo novo)
│   └── preset_mapping.json     # extensão→plugin, categorias de preset (pipeline novo)
└── diagnose_rejected.py        # diagnóstico standalone de arquivos corrompidos
```

**Por que dois scripts separados, não um `--mode`**: `migrate_samples.py`
já rodou de verdade (Ciclo 1) — qualquer edição nele, por menor que seja,
arrisca código já validado. O pipeline de MIDI+Presets é 100% aditivo,
zero import de `audio_analyzer.py`/`file_organizer.py`/`reporter.py`. As
únicas coisas que ele reaproveita do lado do áudio são leituras
**somente-leitura** de `config/genre_mapping.json` (taxonomia de gênero e
os padrões de regex de BPM/key, já corrigidos) e `modules/benchmark.py`
(genérico, sem nada específico de áudio).

**As 6 fases de cada execução** (mesma estrutura nos dois pipelines):
1. **Descoberta** — lista os arquivos da pasta fonte pela extensão relevante
2. **Calibração automática** — testa números de workers candidatos contra
   arquivos reais desta pasta/disco, escolhe o mais rápido por fase
3. **Validação** — integridade + hash MD5 (dedup e desambiguação de colisão), paralela (threads)
4. **Análise** — metadados específicos de cada tipo de arquivo, paralela (processos)
5. **Migração** — copia pro destino com nome final, na estrutura de pastas
6. **Relatório** — gera CSV, JSON e HTML com o resultado

---

## 4. O que já foi feito

### 4.1 Pipeline de áudio — base
- Taxonomia Loop/Oneshot/FX por comportamento (onsets, ponto de loop, envelope), não duração pura
- BPM só em `Loop`, tonalidade suprimida em percussão sem afinação, sem dados fabricados
- Brilho espectral (Escuro/Medio/Claro/Full_Spectro) como dimensão nova de metadado
- Paralelismo com auto-calibração (`modules/benchmark.py`) — sem número fixo hardcoded
- Diagnóstico: 100% dos arquivos corrompidos concentrados em 5 pastas da marca "Exotic Refreshment"

### 4.2 Pipeline de MIDI + Presets — construído do zero nesta sessão
- Árvore de destino separada (`KOLBIE PRESETS:MIDI`), nunca aninhada dentro de `KOLBIE SAMPLES`
- MIDI: tempo/compasso exatos via meta-evento quando existe; fallback por nome de arquivo quando não (93,5% dos `.mid` reais não têm meta-evento de tempo)
- Tonalidade: prioridade pro nome do arquivo (`Cmin`/`F#maj`) sobre a heurística de notas — nome é intenção explícita do produtor, heurística é estatística
- Presets: Tier A (Serum/Vital/sfz — parse real de conteúdo) e Tier B (binários sem doc — copia + indexa por nome/extensão, sem tentar decodificar)
- Categoria por abreviação de nome de arquivo (`PD`→Pad, `SQ`→Sequence, `BS`→Bass, 16 categorias) — pesquisado contra convenções reais de empresas de sample pack e validado contra a biblioteca
- Gênero reaproveitado do `genre_mapping.json` (somente leitura) — mesma taxonomia das duas árvores
- Desambiguação de colisão por hash MD5 — nome repetido com conteúdo diferente nunca é descartado

### 4.3 Bugs corrigidos no pipeline de áudio (achados testando de verdade, não só lendo código)
- **Drums engolindo tudo**: `type_keywords` de Drums incluía `"loop"`/`"break"` — qualquer arquivo com "Loop" no nome (Lead, Bass, Synth, Arp, Pad) virava Drums. 47,8% da biblioteca estava em Drums por causa disso; corrigido, ficou 36,8% mais os valores reais realocados pra Leads/Bass/Pads.
- **BPM fabricado de número de faixa**: o padrão de regex de BPM mais usado tinha um fallback genérico que casava com qualquer número de 2-3 dígitos, sem exigir a palavra "bpm" por perto. 75% dos "BPMs" extraídos eram número de faixa/catálogo, não tempo.
- **Tonalidade fabricada de letra solta**: um padrão de regex de key casava com qualquer letra sozinha antes de espaço/underscore. 100% de uma amostra real eram falsos positivos (`ALPHA WET` → tonalidade "A").
- **Convenção `Cmin`/`D#Maj` nunca reconhecida**: nome completo de nota + modo, presente em 932 arquivos de áudio e 273 de MIDI/presets, não tinha nenhum padrão de regex que capturasse.
- **BPM/key lendo o caminho completo**: mesma classe de bug já corrigida em `_extract_type_from_name`, mas nunca aplicada a BPM/key até agora — corrigido pra ler só o nome do arquivo.
- **Tags de gênero ID3 sem normalização**: `existing_metadata['genre']` usava o valor cru gravado no arquivo, gerando pastas soltas ("Melodic House & Techno") ao lado das curadas. Agora passa pela mesma busca por palavra-chave do nome do arquivo.
- **Taxonomia de subgênero achatada**: Melodic House/Techno, Deep/Minimal/Progressive/Tech/Slap/Afro House, Dub Techno, Big Room, Reggaeton, Funk, Afrobeat, Nu Disco, Disco, Synthwave, LoFi, Hardstyle, Garage, Tribal — todos caíam no genérico (House/Techno/Outros). Separados como categorias próprias após varredura confirmando packs reais nas 3 pastas fonte.
- **Colisão de nome descartando arquivo**: `FileOrganizer.copy_file()` só checava se o destino existia, sem comparar conteúdo — nome repetido com conteúdo diferente (confirmado real: `Perc.wav` tem 5 conteúdos distintos em 9 cópias na biblioteca) era descartado silenciosamente. Corrigido com a mesma desambiguação por hash já usada no pipeline novo.
- `genre_mappings` (dict morto no config, nunca chamado em código nenhum) removido — a ordenação corrigida do `genre_keywords` (mais específico primeiro) resolve a mesma coisa sem duplicar taxonomia.

---

## 5. Roteiro de execução (o que falta)

Estado atual: as duas pastas de destino (`KOLBIE SAMPLES` e
`KOLBIE PRESETS:MIDI`) foram **esvaziadas** para rodar do zero com todas as
correções acima. Pilotos de validação (dry-run + cópia real) já rodaram nas
3 pastas fonte para os dois pipelines, sem erro de processo.

**Passo obrigatório antes de qualquer ciclo novo**: rodar
`python3 audit_genre_coverage.py --all-known-sources` e revisar a lista de
pastas-pack usadas como fallback — se algum nome ali for na verdade um
estilo/gênero real (ex.: "Bachata Pura" antes de virar keyword "Bachata"),
cadastrar em `config/genre_mapping.json` antes de migrar, não depois.
Gênero sem keyword cadastrada nunca cai mais em "Outros" genérico — usa o
nome da pasta-pack original (`_fallback_genre_from_pack` em
`audio_analyzer.py`); "Outros" literal só ocorre pra arquivo solto direto
na raiz da pasta fonte, sem nenhuma pasta acima (2 casos reais nas 3
pastas fonte, ver auditoria).

Quando o nome do pack é de artista/label/empresa (não descreve o estilo
diretamente, ex. "Deadmau5", "KSHMR"), a pesquisa é feita na internet e o
resultado vira uma entrada em `pack_genre_overrides` (config/genre_mapping.json)
— nome exato da pasta → gênero real, checado antes do fallback puro pelo
nome da pasta. 14 packs já pesquisados e resolvidos (10.747 arquivos de
KSHMR → Big Room, 2.926 de Deadmau5 → Progressive House, etc. — rodar
`audit_genre_coverage.py` mostra a lista completa). Os que sobram no topo
do fallback (Maschine Samples, Thomas Penton, Elemental Studio Percussion,
Vengeance Sounds Effects...) são bibliotecas de instrumento/percussão/FX
multi-gênero por natureza — pesquisa adicional tende a confirmar "sem
gênero único", não destravar mais volume.

### Ciclo 1 — `-ELETRONIC MUSIC-`

**Áudio:**
```bash
cd ~/kolbie-samples-migrate
python3 migrate_samples.py \
  --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" \
  --destination "/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES" \
  --verbose
```

**MIDI + Presets:**
```bash
python3 migrate_midi_presets.py \
  --source-dir "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-" \
  --verbose
```
- **Status**: pronto, aguardando aprovação final pra rodar de verdade
- **Pós-ciclo**: revisar amostra de arquivos copiados nas duas árvores, checar CSV/HTML gerado em cada uma

**Teste de amostra real feito em 2026-07-23** (destinos limpos antes,
`--sample-size 500`, sem `--dry-run`, nos dois pipelines, log completo
revisado fase por fase): 500/500 válidos, 0 duplicados, 0 falhas, 0
`Outros` na distribuição de gênero nos dois, hash MD5 de 8 arquivos
aleatórios idêntico entre original e cópia. Nenhum erro/traceback em
nenhuma fase. **Destinos ainda contêm esses 500 arquivos de teste** (não
foram limpos de novo depois) — precisa esvaziar de novo antes de rodar o
Ciclo 1 completo (todos os ~13k áudio + ~2k MIDI/presets desta pasta).

### Ciclo 2 — `SAMPLES ABLETON`
Mesmos dois comandos, trocando `--source-dir`. Maior pasta (153.977
arquivos) — tempo real depende do que a calibração automática encontrar.
Fumaça já testada (dry-run) nesta sessão, sem erro.

### Ciclo 3 — `NEW SAMPLES N PRESETS`
Mesmos dois comandos. Fumaça já testada (dry-run) nesta sessão, sem erro.

### Pós-migração (todos os 3 ciclos concluídos, nos dois pipelines)
- [ ] Revisar estrutura final completa nas duas árvores de destino
- [ ] Conferir amostra de arquivos com hash MD5 (original vs. cópia)
- [ ] Decidir se apaga as pastas fonte originais ou mantém como backup
- [ ] Consolidar os relatórios (CSV/JSON/HTML) das 6 rodadas (3 ciclos × 2 pipelines), se necessário

---

## 6. Riscos conhecidos e mitigação

| Risco | Mitigação |
|---|---|
| Perda de dados | Cópia apenas — original nunca é tocado |
| Disco cheio no destino | ~440GB disponíveis nas duas árvores de destino |
| Arquivo corrompido interrompe o processo | Validação isola e reporta, não trava o pipeline |
| Número de workers errado trava/desperdiça CPU | Auto-calibração testa antes de cada rodada real |
| Nome de arquivo muito longo (limite do macOS) | Truncamento automático com `[...]` |
| Colisão de nome com conteúdo diferente | Desambiguação por hash MD5 nos dois pipelines |
| Gênero/tipo classificado errado por keyword genérica | Testado e corrigido nesta sessão (ver 4.3) |

---

## 7. Pendências sinalizadas (não aprovadas ainda)

- `.ncw`/`.rx2` (~8.700 arquivos de áudio real em formato proprietário) —
  **decidido: fora de escopo, não vamos usar.**
- Avisos do `librosa` (`n_fft too large`) em amostras muito curtas —
  não trava nada, só pode reduzir um pouco a precisão do brilho espectral
  nesses casos específicos. Baixa prioridade.

---

## 8. Links

- Repositório: https://github.com/kolbiemusic/kolbie-samples-organizer
- Rationale técnico completo: [DECISIONS.md](./DECISIONS.md)
- Instruções de uso: [README.md](./README.md)

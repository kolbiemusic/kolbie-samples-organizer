#!/bin/bash
set -uo pipefail
cd ~/kolbie-samples-migrate
DEST_AUDIO="/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES"
DEST_MIDI="/Volumes/SAMPLES & LOOPS/KOLBIE PRESETS:MIDI"
LOG_DIR=~/kolbie-samples-migrate/logs
STAMP=$(date +%Y%m%d_%H%M%S)

declare -a SOURCES=(
  "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-"
  "/Volumes/Gui 2TB Dados/SAMPLES ABLETON"
  "/Volumes/Gui 2TB Dados/NEW SAMPLES N PRESETS"
)

for i in "${!SOURCES[@]}"; do
  CYCLE=$((i+1))
  SRC="${SOURCES[$i]}"
  echo "===== CICLO $CYCLE: $SRC - AUDIO - $(date) ====="
  python3 migrate_samples.py --source-dir "$SRC" --destination "$DEST_AUDIO" 2>&1 | tee "$LOG_DIR/cycle${CYCLE}_audio_${STAMP}.log"
  echo "===== CICLO $CYCLE: $SRC - MIDI/PRESETS - $(date) ====="
  python3 migrate_midi_presets.py --source-dir "$SRC" --destination "$DEST_MIDI" 2>&1 | tee "$LOG_DIR/cycle${CYCLE}_midi_${STAMP}.log"
  echo "===== CICLO $CYCLE CONCLUIDO - $(date) ====="
done

echo "===== MIGRACAO COMPLETA - TODOS OS 3 CICLOS - $(date) ====="

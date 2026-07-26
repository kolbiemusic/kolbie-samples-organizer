#!/usr/bin/env python3
import re
import time
import html
from datetime import datetime
from pathlib import Path

LOG = Path.home() / "kolbie-samples-migrate" / "logs" / "full_migration_master.log"
OUT = Path.home() / "kolbie-samples-migrate" / "dashboard" / "dashboard.html"

CYCLE_RE = re.compile(r"===== CICLO (\d+): (.+?) - (AUDIO|MIDI/PRESETS) - ")
CYCLE_DONE_RE = re.compile(r"===== CICLO (\d+) CONCLUIDO")
ALL_DONE_RE = re.compile(r"MIGRACAO COMPLETA")
PHASE_RE = re.compile(r"PHASE (\d): ([A-Z /&]+)")
FOUND_RE = re.compile(r"Found (\d+) (?:audio )?files?")
COPIED_RE = re.compile(r"Copied: (\d+)")
SKIPPED_RE = re.compile(r"Skipped \(already migrated\): (\d+)")
FAILED_RE = re.compile(r"Failed: (\d+)")
PREFLIGHT_RE = re.compile(r"PRE-FLIGHT: (\d+) pacote")
EXTRACT_RE = re.compile(r"Extraindo (.+?) \(")

def render(state):
    cycle = state.get("cycle", "-")
    src = html.escape(state.get("src", "-"))
    pipeline = state.get("pipeline", "-")
    phase = html.escape(state.get("phase", "Iniciando..."))
    found = state.get("found")
    preflight = state.get("preflight")
    extracting = state.get("extracting")
    copied = state.get("copied")
    skipped = state.get("skipped")
    failed = state.get("failed")
    done = state.get("all_done", False)
    cycles_done = state.get("cycles_done", [])

    badge = "badge-done" if done else "badge-running"
    status = "Concluído" if done else "Rodando"

    extra = ""
    if preflight is not None:
        extra += f'<div class="found">Pre-flight: {preflight} pacote(s) compactado(s) encontrado(s)</div>'
    if extracting:
        extra += f'<div class="found">Extraindo agora: {html.escape(extracting)}</div>'
    if found is not None:
        extra += f'<div class="found">{found} arquivos encontrados</div>'
    if copied is not None or skipped is not None or failed is not None:
        extra += (
            '<div class="summary">'
            f'<span class="stat stat-ok">Copiados: {copied if copied is not None else "-"}</span>'
            f'<span class="stat stat-skip">Pulados: {skipped if skipped is not None else "-"}</span>'
            f'<span class="stat stat-fail">Falhas: {failed if failed is not None else "-"}</span>'
            '</div>'
        )

    cycles_html = ""
    if cycles_done:
        items = "".join(f'<li>Ciclo {c} concluído</li>' for c in cycles_done)
        cycles_html = f'<ul style="margin:8px 0 0;padding-left:18px;color:#8e8e93;font-size:13px">{items}</ul>'

    now = datetime.now().strftime("%H:%M:%S")

    return f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>KOLBIE — Progresso da Migração</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", Helvetica, Arial, sans-serif;
    background: #0e0f13; color: #e8e8ec; margin: 0; padding: 32px;
  }}
  @media (prefers-color-scheme: light) {{ body {{ background: #f5f5f7; color: #1c1c1e; }} }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 4px; }}
  .updated {{ color: #8e8e93; font-size: 13px; margin-bottom: 28px; }}
  .panel {{
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px; padding: 20px 24px; margin-bottom: 20px;
  }}
  @media (prefers-color-scheme: light) {{
    .panel {{ background: #fff; border-color: rgba(0,0,0,0.08); box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  }}
  .panel-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }}
  .panel-header h2 {{ font-size: 16px; font-weight: 600; margin: 0; }}
  .badge {{ font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.3px; }}
  .badge-running {{ background: rgba(255, 159, 10, 0.18); color: #ff9f0a; }}
  .badge-done {{ background: rgba(48, 209, 88, 0.18); color: #30d158; }}
  .phase {{ font-size: 13px; color: #8e8e93; margin-bottom: 4px; }}
  .found {{ font-size: 12px; color: #8e8e93; margin-bottom: 6px; }}
  .summary {{ margin-top: 14px; display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat {{ font-size: 13px; font-weight: 500; }}
  .stat-ok {{ color: #30d158; }}
  .stat-skip {{ color: #8e8e93; }}
  .stat-fail {{ color: #ff453a; }}
</style>
</head>
<body>
  <h1>🎵 KOLBIE SAMPLES — Migração Completa (Ciclos 1-3)</h1>
  <div class="updated">Atualizado às {now} · auto-refresh a cada 5s</div>
  <div class="panel">
    <div class="panel-header">
      <h2>Ciclo {cycle} — {src} ({pipeline})</h2>
      <span class="badge {badge}">{status}</span>
    </div>
    <div class="phase">{phase}</div>
    {extra}
    {cycles_html}
  </div>
</body>
</html>
"""

def parse(lines):
    state = {}
    cycles_done = []
    for line in lines:
        m = CYCLE_RE.search(line)
        if m:
            state["cycle"] = m.group(1)
            state["src"] = m.group(2)
            state["pipeline"] = m.group(3)
            state["found"] = None
            state["preflight"] = None
            state["extracting"] = None
            state["copied"] = None
            state["skipped"] = None
            state["failed"] = None
            continue
        m = CYCLE_DONE_RE.search(line)
        if m:
            cycles_done.append(m.group(1))
            continue
        if ALL_DONE_RE.search(line):
            state["all_done"] = True
            continue
        m = PREFLIGHT_RE.search(line)
        if m:
            state["preflight"] = m.group(1)
            continue
        m = EXTRACT_RE.search(line)
        if m:
            state["extracting"] = m.group(1)
            continue
        m = PHASE_RE.search(line)
        if m:
            state["phase"] = f"PHASE {m.group(1)}: {m.group(2).strip()}"
            state["extracting"] = None
            continue
        m = FOUND_RE.search(line)
        if m:
            state["found"] = m.group(1)
            continue
        m = COPIED_RE.search(line)
        if m:
            state["copied"] = m.group(1)
            continue
        m = SKIPPED_RE.search(line)
        if m:
            state["skipped"] = m.group(1)
            continue
        m = FAILED_RE.search(line)
        if m:
            state["failed"] = m.group(1)
            continue
    state["cycles_done"] = cycles_done
    return state

def main():
    last_size = -1
    while True:
        try:
            if LOG.exists():
                text = LOG.read_text(errors="ignore")
                size = len(text)
                if size != last_size:
                    lines = text.splitlines()
                    state = parse(lines)
                    OUT.write_text(render(state))
                    last_size = size
            time.sleep(3)
        except Exception:
            time.sleep(3)

if __name__ == "__main__":
    main()

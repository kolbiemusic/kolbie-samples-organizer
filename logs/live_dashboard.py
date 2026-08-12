#!/usr/bin/env python3
"""Live progress dashboard for the 3-cycle genre-marker migration
(migrate_by_genre.py + migrate_serum_presets.py). Tails
logs/full_migration_master.log and rewrites dashboard/dashboard.html every
~2s with real, parsed progress — no external deps, stdlib only, matching
the rest of the 2026-07-26 rewrite. One progress bar per cycle, each split
into its two phases (audio copy, Serum presets).
"""
import re
import time
import html
from datetime import datetime
from pathlib import Path

LOG = Path.home() / "kolbie-samples-migrate" / "logs" / "full_migration_master.log"
OUT = Path.home() / "kolbie-samples-migrate" / "dashboard" / "dashboard.html"

CYCLE_RE = re.compile(r"===== CICLO (\d+): (.+?) - (AUDIO|SERUM PRESETS) - ")
CYCLE_DONE_RE = re.compile(r"===== CICLO (\d+) CONCLUIDO")
ALL_DONE_RE = re.compile(r"MIGRACAO COMPLETA")
RESOLVED_RE = re.compile(r"Copy units resolved: (\d+)")
PROGRESS_RE = re.compile(r"PROGRESS (\d+)/(\d+)")
AUDIO_SUMMARY_RE = re.compile(
    r"Copied: (\d+)\s+Skipped \(already there\): (\d+)\s+Would copy \(dry-run\): (\d+)\s+Failed: (\d+)"
)
PRESET_SUMMARY_RE = re.compile(
    r"Total: (\d+) copied, (\d+) skipped \(already there\), (\d+) excluded"
)

PHASE_LABEL = {"AUDIO": "Áudio (por gênero)", "PRESETS": "Presets Serum/Serum 2"}


def bar(pct, done):
    pct = max(0, min(100, pct))
    fill_color = "#30d158" if done else "#0a84ff, #64d2ff"
    gradient = fill_color if done else f"linear-gradient(90deg, {fill_color})"
    return (
        '<div class="bar-track">'
        f'<div class="bar-fill" style="width:{pct}%;background:{gradient}"></div>'
        '</div>'
    )


def render_cycle(cnum, cstate):
    src = html.escape(cstate.get("src", ""))
    rows = []
    for phase in ("AUDIO", "PRESETS"):
        p = cstate["phases"].get(phase)
        if not p:
            rows.append(
                f'<div class="phase-row"><span class="phase-name">{PHASE_LABEL[phase]}</span>'
                f'<span class="bar-pct">aguardando…</span></div>'
            )
            continue
        total = p.get("total", 0)
        done_n = p.get("progress", 0)
        finished = p.get("finished", False)
        pct = round(100 * done_n / total) if total else (100 if finished else 0)
        if finished:
            pct = 100
            done_n = total if total else done_n
        label = f"{done_n}/{total} ({pct}%)" if total else ("concluído" if finished else "…")
        rows.append(
            f'<div class="phase-row">'
            f'<span class="phase-name">{PHASE_LABEL[phase]}</span>'
            f'<div class="bar-wrap">{bar(pct, finished)}<span class="bar-pct">{label}</span></div>'
            f'</div>'
        )

    status = cstate.get("status", "pendente")
    badge_class = {"concluído": "badge-done", "rodando": "badge-running", "pendente": "badge-pending"}[status]

    return f"""
    <div class="panel">
      <div class="panel-header">
        <h2>Ciclo {cnum} {f"— {src}" if src else ""}</h2>
        <span class="badge {badge_class}">{status.capitalize()}</span>
      </div>
      {''.join(rows)}
    </div>
    """


def render(cycles, all_done):
    now = datetime.now().strftime("%H:%M:%S")
    panels = "".join(render_cycle(n, cycles[n]) for n in sorted(cycles))
    overall_badge = "badge-done" if all_done else "badge-running"
    overall_status = "Concluída" if all_done else "Em andamento"

    return f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<title>KOLBIE — Migração por Gênero</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", Helvetica, Arial, sans-serif;
    background: #0e0f13; color: #e8e8ec; margin: 0; padding: 32px;
  }}
  @media (prefers-color-scheme: light) {{ body {{ background: #f5f5f7; color: #1c1c1e; }} }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 4px; display: flex; align-items: center; gap: 10px; }}
  .updated {{ color: #8e8e93; font-size: 13px; margin-bottom: 28px; }}
  .panel {{
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px; padding: 20px 24px; margin-bottom: 16px;
  }}
  @media (prefers-color-scheme: light) {{
    .panel {{ background: #fff; border-color: rgba(0,0,0,0.08); box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  }}
  .panel-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }}
  .panel-header h2 {{ font-size: 16px; font-weight: 600; margin: 0; }}
  .badge {{ font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.3px; flex-shrink: 0; }}
  .badge-running {{ background: rgba(255, 159, 10, 0.18); color: #ff9f0a; }}
  .badge-done {{ background: rgba(48, 209, 88, 0.18); color: #30d158; }}
  .badge-pending {{ background: rgba(142, 142, 147, 0.18); color: #8e8e93; }}
  .phase-row {{ display: flex; align-items: center; gap: 14px; margin: 10px 0; }}
  .phase-name {{ width: 190px; flex-shrink: 0; font-size: 13px; color: #aeaeb2; }}
  .bar-wrap {{ display: flex; align-items: center; gap: 10px; flex: 1; }}
  .bar-track {{ flex: 1; height: 10px; background: rgba(255,255,255,0.08); border-radius: 5px; overflow: hidden; }}
  @media (prefers-color-scheme: light) {{ .bar-track {{ background: rgba(0,0,0,0.08); }} }}
  .bar-fill {{ height: 100%; border-radius: 5px; transition: width 0.4s ease; }}
  .bar-pct {{ width: 130px; flex-shrink: 0; font-size: 12px; color: #aeaeb2; text-align: right; }}
</style>
</head>
<body>
  <h1>🎵 KOLBIE — Migração por Gênero <span class="badge {overall_badge}">{overall_status}</span></h1>
  <div class="updated">Atualizado às {now} · auto-refresh a cada 3s</div>
  {panels}
</body>
</html>
"""


def new_cycle_state():
    return {"src": "", "status": "pendente", "phases": {}}


def parse(lines):
    cycles = {1: new_cycle_state(), 2: new_cycle_state(), 3: new_cycle_state()}
    current = None  # (cycle_num, phase)
    all_done = False

    for line in lines:
        m = CYCLE_RE.search(line)
        if m:
            cnum = int(m.group(1))
            phase = "AUDIO" if m.group(3) == "AUDIO" else "PRESETS"
            cycles[cnum]["src"] = m.group(2)
            cycles[cnum]["status"] = "rodando"
            cycles[cnum]["phases"].setdefault(phase, {"total": 0, "progress": 0, "finished": False})
            current = (cnum, phase)
            continue

        m = CYCLE_DONE_RE.search(line)
        if m:
            cnum = int(m.group(1))
            cycles[cnum]["status"] = "concluído"
            for p in cycles[cnum]["phases"].values():
                p["finished"] = True
            current = None
            continue

        if ALL_DONE_RE.search(line):
            all_done = True
            continue

        if current is None:
            continue
        cnum, phase = current
        p = cycles[cnum]["phases"][phase]

        m = RESOLVED_RE.search(line)
        if m:
            p["total"] = int(m.group(1))
            continue

        m = PROGRESS_RE.search(line)
        if m:
            p["progress"] = int(m.group(1))
            p["total"] = int(m.group(2))
            continue

        if AUDIO_SUMMARY_RE.search(line) or PRESET_SUMMARY_RE.search(line):
            p["finished"] = True
            continue

    return cycles, all_done


def main():
    last_size = -1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            if LOG.exists():
                text = LOG.read_text(errors="ignore")
                size = len(text)
                if size != last_size:
                    lines = text.splitlines()
                    cycles, all_done = parse(lines)
                    OUT.write_text(render(cycles, all_done))
                    last_size = size
            time.sleep(2)
        except Exception:
            time.sleep(2)


if __name__ == "__main__":
    main()

"""
CSV/JSON/HTML report generation for the MIDI + Presets pipeline.

Sibling to Reporter, not a reuse of it — Reporter.generate_csv_index() and
generate_html_report() hardcode audio-specific fieldnames/sections (bpm,
genre, classification...) with zero parameterization, so extending it would
mean editing already-validated code for an unrelated data shape. The
file-writing skeleton (csv.DictWriter, same inline <style> block) is
reproduced here with MIDI+preset fields instead.
"""
import json
import csv
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

CSV_FIELDNAMES = [
    'kind', 'original_filename', 'new_path', 'genre',
    'plugin_family', 'tier', 'preset_name', 'category', 'parse_method', 'parse_confidence',
    'tempo_bpm', 'has_tempo_meta', 'time_signature', 'key', 'key_confidence',
    'num_tracks', 'duration_sec', 'duration_bars',
    'confidence', 'content_hash',
]


class MidiPresetReporter:
    def __init__(self, destination_root):
        self.destination_root = Path(destination_root)
        self.metadata_list = []

    def add_file_metadata(self, metadata):
        self.metadata_list.append(metadata)

    def generate_csv_index(self, filename='KOLBIE_MIDI_PRESETS_INDEX.csv'):
        output_path = self.destination_root / filename
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
                writer.writeheader()

                for metadata in self.metadata_list:
                    row = {field: metadata.get(field, '') for field in CSV_FIELDNAMES}
                    row['original_filename'] = metadata.get('filename', '')
                    for confidence_field in ('parse_confidence', 'key_confidence', 'confidence'):
                        if isinstance(row.get(confidence_field), (int, float)):
                            row[confidence_field] = round(row[confidence_field], 2)
                    writer.writerow(row)

            logger.info(f"CSV index generated: {output_path}")
            return str(output_path)
        except Exception as e:
            logger.error(f"Error generating CSV: {e}")
            return None

    def generate_json_metadata(self, filename='_METADATA/all_files.json'):
        output_path = self.destination_root / filename
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.metadata_list, f, indent=2, ensure_ascii=False)

            logger.info(f"JSON metadata generated: {output_path}")
            return str(output_path)
        except Exception as e:
            logger.error(f"Error generating JSON: {e}")
            return None

    def generate_html_report(self, stats, filename='_DOCUMENTATION/Migration_Report.html'):
        output_path = self.destination_root / filename
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            total_files = len(self.metadata_list)
            midi_entries = [m for m in self.metadata_list if m.get('kind') == 'midi']
            preset_entries = [m for m in self.metadata_list if m.get('kind') == 'preset']

            tempo_ranges = defaultdict(int)
            for m in midi_entries:
                if m.get('has_tempo_meta') and m.get('tempo_bpm'):
                    bpm = m['tempo_bpm']
                    if bpm < 85:
                        tempo_ranges['<85'] += 1
                    elif bpm < 100:
                        tempo_ranges['85-100'] += 1
                    elif bpm < 110:
                        tempo_ranges['100-110'] += 1
                    elif bpm < 120:
                        tempo_ranges['110-120'] += 1
                    elif bpm < 130:
                        tempo_ranges['120-130'] += 1
                    elif bpm < 145:
                        tempo_ranges['130-145'] += 1
                    elif bpm < 160:
                        tempo_ranges['145-160'] += 1
                    else:
                        tempo_ranges['160+'] += 1
                else:
                    tempo_ranges['unknown_tempo'] += 1

            plugin_families = defaultdict(int)
            tiers = defaultdict(int)
            for m in preset_entries:
                plugin_families[m.get('plugin_family', 'Unknown_Plugin')] += 1
                tiers[m.get('tier', 'B_indexed')] += 1

            genres = defaultdict(int)
            categories = defaultdict(int)
            for m in self.metadata_list:
                genres[m.get('genre', 'Outros')] += 1
                categories[m.get('category', 'Uncategorized')] += 1

            def _table_rows(counter, total):
                rows = ""
                for key in sorted(counter.keys()):
                    pct = (counter[key] / total * 100) if total > 0 else 0
                    rows += f"<tr><td>{key}</td><td>{counter[key]}</td><td>{pct:.1f}%</td></tr>"
                return rows

            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>KOLBIE PRESETS:MIDI - Migration Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        h1, h2 {{ color: #333; }}
        table {{ width: 100%; border-collapse: collapse; background-color: white; margin-bottom: 20px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:hover {{ background-color: #f9f9f9; }}
        .stat-box {{ background-color: white; padding: 15px; border-left: 4px solid #4CAF50; margin-bottom: 15px; }}
        .stat-box h3 {{ margin: 0; color: #4CAF50; }}
        .stat-box .number {{ font-size: 24px; font-weight: bold; color: #333; }}
    </style>
</head>
<body>
    <h1>🎹 KOLBIE PRESETS:MIDI - Migration Report</h1>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

    <div class="stat-box"><h3>Total Files Processed</h3><div class="number">{total_files}</div></div>
    <div class="stat-box"><h3>MIDI Files</h3><div class="number">{len(midi_entries)}</div></div>
    <div class="stat-box"><h3>Preset Files</h3><div class="number">{len(preset_entries)}</div></div>
    <div class="stat-box"><h3>Files Copied</h3><div class="number">{stats.get('copied', 0)}</div></div>
    <div class="stat-box"><h3>Skipped (already migrated)</h3><div class="number">{stats.get('skipped', 0)}</div></div>
    <div class="stat-box"><h3>Failed Copies</h3><div class="number">{stats.get('failed', 0)}</div></div>

    <h2>MIDI — Distribution by Tempo Range</h2>
    <table>
        <tr><th>Tempo Range</th><th>Count</th><th>Percentage</th></tr>
        {_table_rows(tempo_ranges, len(midi_entries))}
    </table>

    <h2>Presets — Distribution by Plugin Family</h2>
    <table>
        <tr><th>Plugin Family</th><th>Count</th><th>Percentage</th></tr>
        {_table_rows(plugin_families, len(preset_entries))}
    </table>

    <h2>Presets — Distribution by Tier</h2>
    <table>
        <tr><th>Tier</th><th>Count</th><th>Percentage</th></tr>
        {_table_rows(tiers, len(preset_entries))}
    </table>

    <h2>Distribution by Genre (MIDI + Presets)</h2>
    <table>
        <tr><th>Genre</th><th>Count</th><th>Percentage</th></tr>
        {_table_rows(genres, total_files)}
    </table>

    <h2>Distribution by Category (MIDI + Presets)</h2>
    <table>
        <tr><th>Category</th><th>Count</th><th>Percentage</th></tr>
        {_table_rows(categories, total_files)}
    </table>
</body>
</html>
"""

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            logger.info(f"HTML report generated: {output_path}")
            return str(output_path)
        except Exception as e:
            logger.error(f"Error generating HTML report: {e}")
            return None

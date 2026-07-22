import json
import csv
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

class Reporter:
    def __init__(self, destination_root):
        self.destination_root = Path(destination_root)
        self.metadata_list = []
        self.stats = defaultdict(int)

    def add_file_metadata(self, metadata):
        """Add file metadata to report"""
        self.metadata_list.append(metadata)

    def generate_csv_index(self, filename='KOLBIE_SAMPLES_INDEX.csv'):
        """Generate CSV index of all files"""
        output_path = self.destination_root / filename
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ['original_filename', 'new_path', 'bpm', 'key', 'brightness', 'genre', 'type', 'classification', 'duration_sec', 'confidence']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for metadata in self.metadata_list:
                    writer.writerow({
                        'original_filename': metadata.get('filename', ''),
                        'new_path': metadata.get('new_path', ''),
                        'bpm': metadata.get('bpm', ''),
                        'key': metadata.get('key', ''),
                        'brightness': metadata.get('brightness', ''),
                        'genre': metadata.get('genre', ''),
                        'type': metadata.get('type', ''),
                        'classification': metadata.get('classification', ''),
                        'duration_sec': metadata.get('duration_sec', ''),
                        'confidence': round(metadata.get('confidence', 0), 2)
                    })

            logger.info(f"CSV index generated: {output_path}")
            return str(output_path)
        except Exception as e:
            logger.error(f"Error generating CSV: {e}")
            return None

    def generate_json_metadata(self, filename='_METADATA/all_files.json'):
        """Generate JSON metadata file"""
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
        """Generate HTML migration report"""
        output_path = self.destination_root / filename
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Gather statistics
            total_files = len(self.metadata_list)
            genres = defaultdict(int)
            types = defaultdict(int)
            classifications = defaultdict(int)
            bpm_ranges = defaultdict(int)

            for metadata in self.metadata_list:
                if metadata.get('genre'):
                    genres[metadata['genre']] += 1
                if metadata.get('type'):
                    types[metadata['type']] += 1
                if metadata.get('classification'):
                    classifications[metadata['classification']] += 1
                if metadata.get('bpm'):
                    bpm = metadata['bpm']
                    if 70 <= bpm < 85:
                        bpm_ranges['70-85'] += 1
                    elif 85 <= bpm < 100:
                        bpm_ranges['85-100'] += 1
                    elif 100 <= bpm < 110:
                        bpm_ranges['100-110'] += 1
                    elif 110 <= bpm < 120:
                        bpm_ranges['110-120'] += 1
                    elif 120 <= bpm < 130:
                        bpm_ranges['120-130'] += 1
                    elif 130 <= bpm < 145:
                        bpm_ranges['130-145'] += 1
                    elif 145 <= bpm < 160:
                        bpm_ranges['145-160'] += 1
                    else:
                        bpm_ranges['160+'] += 1

            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>KOLBIE SAMPLES - Migration Report</title>
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
    <h1>🎵 KOLBIE SAMPLES - Migration Report</h1>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

    <div class="stat-box">
        <h3>Total Files Processed</h3>
        <div class="number">{total_files}</div>
    </div>

    <div class="stat-box">
        <h3>Files Copied</h3>
        <div class="number">{stats.get('copied', 0)}</div>
    </div>

    <div class="stat-box">
        <h3>Failed Copies</h3>
        <div class="number">{stats.get('failed', 0)}</div>
    </div>

    <h2>Distribution by Genre</h2>
    <table>
        <tr><th>Genre</th><th>Count</th><th>Percentage</th></tr>
"""
            for genre in sorted(genres.keys()):
                percentage = (genres[genre] / total_files * 100) if total_files > 0 else 0
                html_content += f"<tr><td>{genre}</td><td>{genres[genre]}</td><td>{percentage:.1f}%</td></tr>"

            html_content += """
    </table>

    <h2>Distribution by Type</h2>
    <table>
        <tr><th>Type</th><th>Count</th><th>Percentage</th></tr>
"""
            for type_name in sorted(types.keys()):
                percentage = (types[type_name] / total_files * 100) if total_files > 0 else 0
                html_content += f"<tr><td>{type_name}</td><td>{types[type_name]}</td><td>{percentage:.1f}%</td></tr>"

            html_content += """
    </table>

    <h2>Distribution by Classification</h2>
    <table>
        <tr><th>Classification</th><th>Count</th><th>Percentage</th></tr>
"""
            for classification in sorted(classifications.keys()):
                percentage = (classifications[classification] / total_files * 100) if total_files > 0 else 0
                html_content += f"<tr><td>{classification}</td><td>{classifications[classification]}</td><td>{percentage:.1f}%</td></tr>"

            html_content += """
    </table>

    <h2>Distribution by BPM Range</h2>
    <table>
        <tr><th>BPM Range</th><th>Count</th><th>Percentage</th></tr>
"""
            for bpm_range in sorted(bpm_ranges.keys()):
                percentage = (bpm_ranges[bpm_range] / total_files * 100) if total_files > 0 else 0
                html_content += f"<tr><td>{bpm_range}</td><td>{bpm_ranges[bpm_range]}</td><td>{percentage:.1f}%</td></tr>"

            html_content += """
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

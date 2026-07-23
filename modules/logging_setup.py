"""
Logging setup for migrate_midi_presets.py.

This is a standalone copy of the same colorlog + tqdm-friendly console/file
handler pattern used by migrate_samples.py's setup_logging() — not a refactor
of it. migrate_samples.py calls its own setup_logging() at import time,
before argparse even runs, so --verbose there is parsed but never actually
applied. That's already-validated, already-run code (Cycle 1); left
untouched on purpose. Here, setup_logging() is called from main() *after*
parse_args(), so --verbose works as documented.
"""
import logging
from pathlib import Path
import colorlog


def setup_logging(verbose=False, log_dir='logs', log_filename='migration_midi_presets.log'):
    Path(log_dir).mkdir(exist_ok=True)

    log_level = logging.DEBUG if verbose else logging.INFO

    console_handler = colorlog.StreamHandler()
    console_handler.setFormatter(colorlog.ColoredFormatter(
        '%(log_color)s[%(levelname)s]%(reset)s %(message)s',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    ))

    file_handler = logging.FileHandler(f'{log_dir}/{log_filename}')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return logging.getLogger('migrate_midi_presets')

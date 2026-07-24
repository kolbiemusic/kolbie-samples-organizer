"""Pre-flight archive extraction: finds still-compressed pack folders under a
source directory, extracts them in place, and — only after a verified
successful extraction — moves the archive files to the macOS Trash (never a
permanent delete; the user can restore or empty the Trash themselves).

Handles single .rar/.zip/.7z, old-style multi-volume RAR (.rar + .r00, .r01,
...), and .partN.rar sets — all parts of a set are extracted together and
trashed together, only if extraction succeeds.
"""
import logging
import re
import subprocess
import zipfile
from pathlib import Path

logger = logging.getLogger('kolbie_migration')

PART_RAR_RE = re.compile(r'^(?P<stem>.+)\.part(?P<num>\d+)\.rar$', re.IGNORECASE)
OLD_MULTIVOL_RE = re.compile(r'^(?P<stem>.+)\.r(?P<num>\d{2})$', re.IGNORECASE)
SEVENZ_MULTIVOL_RE = re.compile(r'^(?P<stem>.+)\.7z\.(?P<num>\d{3})$', re.IGNORECASE)


def _group_archives(source_dir):
    """Walk source_dir, group related archive files (multi-part sets included),
    and pick a primary file per group to hand to the extractor.
    Returns a list of dicts: {'primary': Path, 'members': [Path, ...], 'kind': 'rar'|'zip'|'7z'}."""
    source_path = Path(source_dir)
    all_paths = [p for p in source_path.rglob('*') if p.is_file()]

    groups = {}  # key: (parent_dir, group_stem) -> group dict

    for p in all_paths:
        name = p.name
        parent = p.parent

        m = PART_RAR_RE.match(name)
        if m:
            key = (parent, m.group('stem').lower(), 'rar')
            g = groups.setdefault(key, {'members': [], 'kind': 'rar', 'parts': {}})
            g['members'].append(p)
            g['parts'][int(m.group('num'))] = p
            continue

        m = OLD_MULTIVOL_RE.match(name)
        if m:
            key = (parent, m.group('stem').lower(), 'rar')
            g = groups.setdefault(key, {'members': [], 'kind': 'rar', 'parts': {}})
            g['members'].append(p)
            continue

        m = SEVENZ_MULTIVOL_RE.match(name)
        if m:
            key = (parent, m.group('stem').lower(), '7z')
            g = groups.setdefault(key, {'members': [], 'kind': '7z', 'parts': {}})
            g['members'].append(p)
            g['parts'][int(m.group('num'))] = p
            continue

        if name.lower().endswith('.rar'):
            key = (parent, p.stem.lower(), 'rar')
            g = groups.setdefault(key, {'members': [], 'kind': 'rar', 'parts': {}})
            g['members'].append(p)
            g['parts'][0] = p  # plain .rar is always the entry point for old-style sets
            continue

        if name.lower().endswith('.zip'):
            key = (parent, p.stem.lower(), 'zip')
            g = groups.setdefault(key, {'members': [], 'kind': 'zip', 'parts': {}})
            g['members'].append(p)
            g['parts'][0] = p
            continue

        if name.lower().endswith('.7z'):
            key = (parent, p.stem.lower(), '7z')
            g = groups.setdefault(key, {'members': [], 'kind': '7z', 'parts': {}})
            g['members'].append(p)
            g['parts'][0] = p
            continue

    results = []
    for (parent, stem, kind), g in groups.items():
        if not g['parts']:
            logger.warning(f"Conjunto de arquivo compactado incompleto (sem parte inicial), ignorando: {g['members']}")
            continue
        primary = g['parts'][min(g['parts'].keys())]
        results.append({'primary': primary, 'members': sorted(set(g['members'])), 'kind': kind, 'folder': parent})

    return results


def _extract_group(group):
    """Extract one archive group in place. Returns True on verified success."""
    primary = group['primary']
    folder = group['folder']
    kind = group['kind']

    if kind == 'rar':
        cmd = ['unar', '-f', '-o', str(folder), str(primary)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            logger.error(f"Falha ao extrair {primary.name} (unar exit {proc.returncode}): {proc.stderr.strip()[-500:]}")
            return False
        return True

    if kind == 'zip':
        try:
            with zipfile.ZipFile(primary) as zf:
                zf.extractall(folder)
            return True
        except Exception as e:
            logger.warning(f"zipfile falhou em {primary.name} ({e}), tentando unar...")
            proc = subprocess.run(['unar', '-f', '-o', str(folder), str(primary)], capture_output=True, text=True)
            if proc.returncode != 0:
                logger.error(f"Falha ao extrair {primary.name} (unar exit {proc.returncode}): {proc.stderr.strip()[-500:]}")
                return False
            return True

    if kind == '7z':
        proc = subprocess.run(['unar', '-f', '-o', str(folder), str(primary)], capture_output=True, text=True)
        if proc.returncode != 0:
            logger.error(f"Falha ao extrair {primary.name} (unar exit {proc.returncode}): {proc.stderr.strip()[-500:]}")
            return False
        return True

    logger.error(f"Tipo de arquivo compactado desconhecido: {kind} ({primary})")
    return False


def _move_to_trash(paths):
    """Move files to the macOS Trash (reversible), via the native /usr/bin/trash
    CLI — moves each file straight to its own volume's .Trashes at the syscall
    level, no Finder/AppleScript dialogs (those block on external volumes)."""
    if not paths:
        return
    proc = subprocess.run(['/usr/bin/trash'] + [str(p) for p in paths], capture_output=True, text=True)
    if proc.returncode != 0:
        logger.warning(f"Falha ao mover para a Lixeira ({proc.returncode}): {proc.stderr.strip()[-500:]}")


def preflight_extract_archives(source_dir, dry_run=False):
    """Find, extract, and trash still-compressed archives under source_dir.
    Runs before file discovery so newly-extracted content is picked up by
    the same migration pass. No-op (report only) when dry_run is True."""
    groups = _group_archives(source_dir)

    if not groups:
        logger.info("Pre-flight: nenhum arquivo compactado (.rar/.zip/.7z) encontrado.")
        return {'extracted': 0, 'failed': 0, 'trashed_files': 0}

    logger.info("=" * 60)
    logger.info(f"PRE-FLIGHT: {len(groups)} pacote(s) compactado(s) encontrado(s)")
    logger.info("=" * 60)

    if dry_run:
        for g in groups:
            logger.info(f"[dry-run] Extrairia: {g['primary'].name} ({len(g['members'])} parte(s)) em {g['folder']}")
        return {'extracted': 0, 'failed': 0, 'trashed_files': 0, 'would_extract': len(groups)}

    extracted = 0
    failed = 0
    trashed_files = 0

    for g in groups:
        logger.info(f"Extraindo {g['primary'].name} ({len(g['members'])} parte(s))...")
        ok = _extract_group(g)
        if ok:
            extracted += 1
            _move_to_trash(g['members'])
            trashed_files += len(g['members'])
            logger.info(f"  ✓ Extraído e movido para a Lixeira: {[m.name for m in g['members']]}")
        else:
            failed += 1
            logger.warning(f"  ✗ Extração falhou, arquivo(s) mantido(s) intocado(s): {[m.name for m in g['members']]}")

    logger.info(f"Pre-flight concluído: {extracted} extraído(s), {failed} falha(s), {trashed_files} arquivo(s) movido(s) para a Lixeira")
    return {'extracted': extracted, 'failed': failed, 'trashed_files': trashed_files}

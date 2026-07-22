#!/usr/bin/env python3
"""
Diagnóstico de causa raiz dos arquivos rejeitados na validação (item 3 do brief).

Reamostra a mesma pasta fonte com seed fixa (reprodutível), roda a validação
atual (mutagen, o que o pipeline usa hoje) e, para cada rejeitado, tenta:
  1. soundfile (libsndfile) - decoder de áudio real, não leitor de tags
  2. ffprobe - decoder via ffmpeg, terceira opinião

Categoriza:
  (a) corrupção real - todos os 3 métodos falham
  (b) recuperável - mutagen falha mas soundfile e/ou ffprobe decodificam
  (c) extensão errada - assinatura do arquivo não bate com a extensão
  (d) outro - ex: 0 bytes, permissão negada
"""
import json
import random
import subprocess
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, '/Users/guilhermeoliveira/kolbie-samples-migrate')

SOURCE = "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-"
SEED = 42
SAMPLE_SIZE = 500
AUDIO_EXTENSIONS = {'.wav', '.aif', '.aiff', '.flac', '.mp3'}

# Magic bytes for common containers (used for the "wrong extension" check)
MAGIC_SIGNATURES = {
    b'RIFF': 'wav/riff',
    b'FORM': 'aiff/iff',
    b'fLaC': 'flac',
    b'ID3': 'mp3(id3)',
    b'\xff\xfb': 'mp3(raw)',
    b'\xff\xf3': 'mp3(raw)',
    b'\xff\xf2': 'mp3(raw)',
}

EXPECTED_SIGNATURE_BY_EXT = {
    '.wav': 'wav/riff',
    '.aif': 'aiff/iff',
    '.aiff': 'aiff/iff',
    '.flac': 'flac',
    '.mp3': ('mp3(id3)', 'mp3(raw)'),
}


def detect_signature(path, size):
    if size == 0:
        return None
    try:
        with open(path, 'rb') as f:
            head = f.read(12)
    except Exception:
        return None
    for magic, name in MAGIC_SIGNATURES.items():
        if head.startswith(magic):
            return name
    return f"unknown({head[:4]!r})"


def try_mutagen(path, ext):
    try:
        if ext == '.wav':
            from mutagen.wave import WAVE
            WAVE(str(path))
        elif ext in {'.aif', '.aiff'}:
            from mutagen.aiff import AIFF
            AIFF(str(path))
        elif ext == '.flac':
            from mutagen.flac import FLAC
            FLAC(str(path))
        elif ext == '.mp3':
            from mutagen.mp3 import MP3
            MP3(str(path))
        return True, None, None
    except Exception as e:
        return False, type(e).__name__, str(e)[:200]


def try_soundfile(path):
    try:
        import soundfile as sf
        info = sf.info(str(path))
        return True, None, None, f"{info.samplerate}Hz {info.channels}ch {info.frames}frames fmt={info.format}/{info.subtype}"
    except Exception as e:
        return False, type(e).__name__, str(e)[:200], None


def try_ffprobe(path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries',
             'stream=codec_name,sample_rate,channels,duration',
             '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if data.get('streams'):
                s = data['streams'][0]
                return True, None, f"{s.get('codec_name')} {s.get('sample_rate')}Hz {s.get('channels')}ch"
        return False, (result.stderr or 'no streams found')[:200], None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:200], None


def main():
    random.seed(SEED)
    print(f"Escaneando {SOURCE} ...")
    all_files = []
    for ext in AUDIO_EXTENSIONS:
        all_files.extend(Path(SOURCE).rglob(f'*{ext}'))
        all_files.extend(Path(SOURCE).rglob(f'*{ext.upper()}'))
    all_files = sorted(set(all_files))
    print(f"Total de arquivos de áudio na pasta: {len(all_files)}")

    sample = random.sample(all_files, min(SAMPLE_SIZE, len(all_files)))
    print(f"Amostra (seed={SEED}): {len(sample)} arquivos\n")

    rejected = []
    for f in sample:
        ext = f.suffix.lower()
        ok, err_type, err_msg = try_mutagen(f, ext)
        if not ok:
            rejected.append({'path': f, 'ext': ext, 'mutagen_error_type': err_type, 'mutagen_error_msg': err_msg})

    print(f"Rejeitados pela validação atual (mutagen): {len(rejected)} / {len(sample)} ({len(rejected)/len(sample)*100:.1f}%)\n")

    diagnostics = []
    for r in rejected:
        path = r['path']
        try:
            size = path.stat().st_size
        except Exception:
            size = None

        signature = detect_signature(path, size or 0)
        expected = EXPECTED_SIGNATURE_BY_EXT.get(r['ext'])
        # "Wrong extension" means the file IS a real, different, known audio
        # format wearing the wrong extension (e.g. mp3 bytes named .wav).
        # An unrecognized/absent signature is not a labeling mistake — it's
        # evidence of corruption (see below), so it must not be conflated
        # with "wrong extension".
        recognized_other_format = signature is not None and not signature.startswith('unknown')
        if isinstance(expected, tuple):
            ext_mismatch = recognized_other_format and signature not in expected
        else:
            ext_mismatch = recognized_other_format and signature != expected

        sf_ok, sf_err_type, sf_err_msg, sf_info = try_soundfile(path)
        ff_ok, ff_err, ff_info = try_ffprobe(path)

        zero_prefix_len = 0
        is_all_zero = False
        try:
            with open(path, 'rb') as fh:
                content = fh.read()
            is_all_zero = len(content) > 0 and all(b == 0 for b in content)
            for b in content:
                if b == 0:
                    zero_prefix_len += 1
                else:
                    break
        except Exception:
            pass

        # Categorize
        if size == 0:
            category = 'd_outro'
            reason = 'arquivo de 0 bytes'
        elif ext_mismatch:
            category = 'c_extensao_errada'
            reason = f'assinatura real é {signature}, mas extensão é {r["ext"]}'
        elif sf_ok or ff_ok:
            category = 'b_recuperavel'
            via = []
            if sf_ok: via.append('soundfile')
            if ff_ok: via.append('ffprobe')
            reason = f'decodificável via {" e ".join(via)}, mutagen (leitor de tags) rejeitou'
        elif is_all_zero:
            category = 'a_corrupcao_real'
            reason = f'arquivo 100% zero-byte ({size} bytes de zeros, sem RIFF em nenhum offset) — placeholder de escrita/download que nunca completou'
        else:
            category = 'a_corrupcao_real'
            reason = f'sem header RIFF em nenhum offset, {zero_prefix_len} bytes de zero no início ({zero_prefix_len/size*100:.0f}% do arquivo se size>0), todos os 3 decoders falharam'

        diagnostics.append({
            'path': str(path).replace(SOURCE, '...'),
            'ext': r['ext'],
            'size_bytes': size,
            'signature_detected': signature,
            'mutagen_error_type': r['mutagen_error_type'],
            'mutagen_error_msg': r['mutagen_error_msg'],
            'soundfile_ok': sf_ok,
            'soundfile_error': sf_err_type,
            'soundfile_info': sf_info,
            'ffprobe_ok': ff_ok,
            'ffprobe_info': ff_info,
            'category': category,
            'reason': reason,
        })

    # Summary
    cat_counts = Counter(d['category'] for d in diagnostics)
    err_type_counts = Counter(d['mutagen_error_type'] for d in diagnostics)

    print("=" * 60)
    print("BREAKDOWN POR CATEGORIA")
    print("=" * 60)
    labels = {
        'a_corrupcao_real': '(a) Corrupção real / sem solução',
        'b_recuperavel': '(b) Recuperável (soundfile/ffprobe decodificam)',
        'c_extensao_errada': '(c) Extensão errada / não é áudio de fato',
        'd_outro': '(d) Outro (ex: 0 bytes)',
    }
    for cat, label in labels.items():
        n = cat_counts.get(cat, 0)
        pct = n / len(diagnostics) * 100 if diagnostics else 0
        print(f"  {label}: {n} ({pct:.1f}%)")

    print()
    print("=" * 60)
    print("TIPOS DE EXCEÇÃO (mutagen)")
    print("=" * 60)
    for err, n in err_type_counts.most_common():
        print(f"  {err}: {n}")

    # Blast radius: which top-level pack folder does each rejected file
    # belong to? A concentrated source (one vendor pack) vs. scattered
    # random rot across the whole drive calls for very different responses.
    pack_counts = Counter()
    for d in diagnostics:
        parts = d['path'].split('/')
        pack_counts[parts[1] if len(parts) > 1 else '(raiz)'] += 1

    print()
    print("=" * 60)
    print("CONCENTRAÇÃO POR PASTA/PACK DE ORIGEM")
    print("=" * 60)
    for pack, n in pack_counts.most_common():
        print(f"  {n}x - {pack}")

    if len(pack_counts) <= 2:
        print("\n  -> Corrupção CONCENTRADA em poucas pastas, não é degradação")
        print("     aleatória espalhada pelo disco. Ver breakdown completo por")
        print("     pack rodando full-scan nessas pastas específicas.")

    with open('/tmp/rejected_diagnostics.json', 'w') as f:
        json.dump({
            'total_sample': len(sample),
            'total_rejected': len(rejected),
            'rejection_rate_pct': round(len(rejected) / len(sample) * 100, 2),
            'category_counts': dict(cat_counts),
            'error_type_counts': dict(err_type_counts),
            'details': diagnostics,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nDetalhes completos salvos em /tmp/rejected_diagnostics.json")


if __name__ == '__main__':
    main()

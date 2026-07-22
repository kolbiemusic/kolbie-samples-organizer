"""
Auto-tuning for parallel worker counts.

The right number of workers isn't a constant — it depends on the CPU
(core count) AND the disk (an external HDD saturates on concurrent reads
well before an 8-core CPU would; an SSD or a fast internal drive might
scale much further). Hardcoding a number tuned on one machine's specific
drive doesn't travel. Instead, before the real run, this times a handful
of candidate worker counts on a small real sample of the actual files
being migrated and picks whichever was fastest — so the number is always
grounded in the machine and disk actually being used, not a guess.
"""
import os
import time
import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

logger = logging.getLogger(__name__)


def candidate_worker_counts():
    """CPU-count-relative candidates to try — adapts to any machine."""
    cpu = os.cpu_count() or 2
    candidates = {1, max(1, cpu // 2), max(1, cpu - 1), cpu}
    return sorted(candidates)


def benchmark_worker_count(sample_files, worker_fn, mode='thread',
                            init_fn=None, init_args=(),
                            min_files_per_candidate=40,
                            label='workers'):
    """
    Time each candidate worker count on real files and return the fastest.
    mode='thread' (I/O-bound work, e.g. validation/hashing) or 'process'
    (CPU-bound work, e.g. audio analysis — needs init_fn to set up
    per-process state, same contract as ProcessPoolExecutor's
    initializer/initargs).

    Returns (best_worker_count, {worker_count: files_per_second}).

    Two confounds to avoid, since both would bias results toward "more
    workers = faster" independent of real throughput:

    1. Equal workload per candidate. Scaling sample size with worker count
       would let a bigger candidate amortize its own (also bigger — more
       processes to spawn) startup cost better than a smaller candidate's,
       making it look faster regardless of real steady-state throughput.
    2. Disjoint files per candidate. Reusing the same subset for every
       candidate means only the first candidate pays real disk I/O — every
       later candidate partly reads from the OS page cache instead, which
       inflates I/O-bound results (validation/hashing) for whichever
       candidate happens to run later. Each candidate gets its own slice
       of files it hasn't touched before, so every measurement reflects a
       genuine cold read.

    Every candidate — including 1 — goes through a real Executor rather
    than a bare loop for mode='process': a bare loop would skip init_fn
    entirely (the worker function needs state only the initializer sets
    up), and it would make "1 worker" artificially cheap since every other
    candidate pays process-spawn/import cost that the bare loop wouldn't.
    """
    candidates = candidate_worker_counts()
    n = max(min_files_per_candidate, max(candidates))  # ensure every worker gets >=1 item even at the largest candidate

    needed = n * len(candidates)
    if len(sample_files) < needed:
        # Not enough files for fully disjoint slices — fall back to a
        # shared subset (repeat what's available). Some cache-reuse bias
        # is better than skipping calibration outright.
        pool = (sample_files * (needed // max(1, len(sample_files)) + 1))[:needed]
    else:
        pool = sample_files[:needed]

    if len(pool) < min_files_per_candidate:
        logger.info(f"Amostra pequena demais pra calibrar ({len(pool)} arquivos) — usando 1 worker.")
        return 1, {}

    results = {}
    Executor = ThreadPoolExecutor if mode == 'thread' else ProcessPoolExecutor

    logger.info(f"Calibrando número de {label} nesta máquina/disco ({n} arquivos por candidato)...")

    for i, workers in enumerate(candidates):
        subset = pool[i * n:(i + 1) * n]
        try:
            kwargs = {}
            if mode == 'process' and init_fn:
                kwargs = {'initializer': init_fn, 'initargs': init_args}

            start = time.perf_counter()
            with Executor(max_workers=workers, **kwargs) as executor:
                list(executor.map(worker_fn, subset))
            elapsed = time.perf_counter() - start

            rate = n / elapsed if elapsed > 0 else 0
            results[workers] = rate
            logger.info(f"  {workers} {label}: {rate:.1f} arquivos/s ({n} arquivos em {elapsed:.1f}s)")
        except Exception as e:
            logger.warning(f"  Calibração falhou com {workers} {label}: {e}")

    if not results:
        logger.warning("Calibração não produziu resultados válidos — usando 1 worker.")
        return 1, {}

    best = max(results, key=results.get)
    logger.info(f"✓ Melhor resultado: {best} {label} ({results[best]:.1f} arquivos/s)")
    return best, results

# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Build, test, and benchmark the agent's MEGAHIT changes on Linux/AArch64."""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path("/results")
RESULT = ROOT / "verifier.json"
BENCHMARK_ID = "megahit-bundled-toy-assembly"
# Compare sequence content without depending on FASTA headers or orientation.
KMER_SIZE = 31
MIN_REFERENCE_COVERAGE = 0.95
MIN_CONTIG_PURITY = 0.95
COMPLEMENT = str.maketrans("ACGT", "TGCA")


def command(name, args, *, cwd=None):
    log = ROOT / f"{name}.log"
    with log.open("w") as output:
        completed = subprocess.run(args, cwd=cwd, stdout=output, stderr=subprocess.STDOUT)
    if completed.returncode:
        raise RuntimeError(f"{name} exited {completed.returncode}; see {log.name}")


def fasta_sequences(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"missing or empty {path}")
    sequences = []
    current = None
    with path.open(encoding="ascii") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if not line[1:].strip() or (current is not None and not current):
                    raise RuntimeError(f"invalid FASTA header in {path}")
                if current is not None:
                    sequences.append("".join(current))
                current = []
            elif current is None or not set(line.upper()) <= set("ACGTN"):
                raise RuntimeError(f"invalid FASTA sequence in {path}")
            else:
                current.append(line.upper())
    if current is None or not current:
        raise RuntimeError(f"missing FASTA sequence in {path}")
    sequences.append("".join(current))
    return sequences


def canonical_kmers(sequence):
    kmers = set()
    for index in range(len(sequence) - KMER_SIZE + 1):
        kmer = sequence[index:index + KMER_SIZE]
        kmers.add(min(kmer, kmer.translate(COMPLEMENT)[::-1]))
    return kmers


def check_assembly(directory, fixture=Path("/fixture/test_data")):
    """Compare assembled output with trusted toy references outside the checkout."""
    contigs = fasta_sequences(directory / "final.contigs.fa")
    references = {}
    for name, filename in (("main", "ref.fa"), ("loop", "loop.fa")):
        kmers = set()
        for sequence in fasta_sequences(fixture / filename):
            kmers.update(canonical_kmers(sequence))
        if not kmers:
            raise RuntimeError(f"{name} reference is shorter than the comparison k-mer")
        references[name] = kmers
    contig_kmers = []
    for index, contig in enumerate(contigs, 1):
        kmers = canonical_kmers(contig)
        purity = (max(len(kmers & reference) / len(kmers)
                      for reference in references.values()) if kmers else 0)
        if purity < MIN_CONTIG_PURITY:
            raise RuntimeError(f"contig {index} does not match the toy references")
        contig_kmers.append(kmers)
    for name, kmers in references.items():
        coverage = max(len(kmers & observed) / len(kmers)
                       for observed in contig_kmers)
        if coverage < MIN_REFERENCE_COVERAGE:
            raise RuntimeError(f"{name} reference coverage in one contig too low: {coverage:.1%}")


def check_aarch64_binary():
    path = ROOT / "build" / "megahit_core"
    with path.open("rb") as binary:
        header = binary.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise RuntimeError(f"{path} is not an ELF executable")
    byte_order = {1: "little", 2: "big"}.get(header[5])
    if byte_order is None or int.from_bytes(header[18:20], byte_order) != 183:
        raise RuntimeError(f"{path} is not an AArch64 executable")


def run_application(name, directory):
    test_data = ROOT / "test_data"
    command(name, [
        "./megahit",
        "--12", str(test_data / "r1.il.fa.gz"),
        "--12", str(test_data / "r2.il.fa.bz2"),
        "-1", str(test_data / "r3_1.fa"),
        "-2", str(test_data / "r3_2.fa"),
        "-r", f"{test_data / 'r4.fa'},{test_data / 'loop.fa'}",
        "-t", "2",
        "-o", str(directory),
    ], cwd=ROOT / "build")


def main():
    stage = "platform"
    try:
        architecture = platform.machine()
        if architecture not in ("aarch64", "arm64"):
            raise RuntimeError(f"expected native AArch64, got {architecture}")
        (ROOT / "test_data").symlink_to("/fixture/test_data")
        stage = "configure"
        build_dir = ROOT / "build"
        build_dir.mkdir()
        command(stage, ["cmake", "-DCMAKE_BUILD_TYPE=Release", "/workspace"],
                cwd=build_dir)
        stage = "build"
        command(stage, ["cmake", "--build", str(ROOT / "build"), "--", "-j2"])
        stage = "binary_architecture"
        check_aarch64_binary()
        stage = "simple_test"
        command(stage, ["cmake", "--build", str(ROOT / "build"), "--target", "simple_test"],
                cwd=ROOT / "build")
        stage = "functional_test"
        run_application(stage, ROOT / "functional")
        check_assembly(ROOT / "functional")
        elapsed = None
        checks = ["linux_aarch64_container", "build", "aarch64_binary",
                  "simple_test", "functional_test", "reference_match"]
        if os.environ["AGENT_EVAL_NATIVE_ARM"] == "1":
            stage = "benchmark"
            started = time.monotonic()
            run_application(stage, ROOT / "benchmark")
            elapsed = round(time.monotonic() - started, 3)
            check_assembly(ROOT / "benchmark")
            checks.append("benchmark")
        verdict = {"success": True, "architecture": architecture,
                   "docker_daemon_architecture": os.environ["AGENT_EVAL_DAEMON_ARCH"],
                   "benchmark_id": BENCHMARK_ID,
                   "application_execution_seconds": elapsed,
                   "checks": checks}
        RESULT.write_text(json.dumps(verdict, indent=2) + "\n")
        print(json.dumps(verdict))
        return 0
    except (OSError, RuntimeError, UnicodeError) as exc:
        verdict = {"success": False, "stage": stage, "error": str(exc)}
        RESULT.write_text(json.dumps(verdict, indent=2) + "\n")
        print(json.dumps(verdict))
        return 1


if __name__ == "__main__":
    sys.exit(main())

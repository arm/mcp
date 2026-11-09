# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Check MEGAHIT toy assemblies against verifier-owned reference data."""

from __future__ import annotations

import random
import runpy
import tempfile
import unittest
from pathlib import Path


VERIFY_INSIDE = (Path(__file__).resolve().parents[1] / "scenarios" /
                 "megahit-arm64" / "verify_inside.py")


def reverse_complement(sequence: str) -> str:
    return sequence.translate(str.maketrans("ACGT", "TGCA"))[::-1]


def write_fasta(path: Path, sequences: list[str]) -> None:
    path.write_text("".join(f">sequence{index}\n{sequence}\n"
                            for index, sequence in enumerate(sequences, 1)),
                    encoding="ascii")


class MegahitAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.fixture = root / "test_data"
        self.fixture.mkdir()
        self.output = root / "assembly"
        self.output.mkdir()
        randomizer = random.Random(2026)
        self.main = "".join(randomizer.choices("ACGT", k=300))
        self.loop = "".join(randomizer.choices("ACGT", k=180))
        write_fasta(self.fixture / "ref.fa", [self.main])
        write_fasta(self.fixture / "loop.fa", [self.loop, self.loop])
        self.check_assembly = runpy.run_path(str(VERIFY_INSIDE))["check_assembly"]

    def write_output(self, *sequences: str) -> None:
        write_fasta(self.output / "final.contigs.fa", list(sequences))

    def test_accepts_reference_sequences_in_either_orientation_and_order(self) -> None:
        self.write_output(reverse_complement(self.loop), self.main)
        self.check_assembly(self.output, self.fixture)

    def test_rejects_arbitrary_fasta_that_passes_syntax_check(self) -> None:
        self.write_output("A")
        with self.assertRaisesRegex(RuntimeError, "does not match the toy references"):
            self.check_assembly(self.output, self.fixture)

    def test_rejects_partial_assembly(self) -> None:
        self.write_output(self.main[:100], self.loop)
        with self.assertRaisesRegex(RuntimeError, "main reference coverage in one contig too low"):
            self.check_assembly(self.output, self.fixture)

    def test_rejects_fragmented_assembly_despite_full_combined_coverage(self) -> None:
        self.write_output(self.main[:130], self.main[100:230],
                          self.main[200:], self.loop)
        with self.assertRaisesRegex(RuntimeError, "main reference coverage in one contig too low"):
            self.check_assembly(self.output, self.fixture)

    def test_rejects_missing_loop_assembly(self) -> None:
        self.write_output(self.main)
        with self.assertRaisesRegex(RuntimeError, "loop reference coverage in one contig too low"):
            self.check_assembly(self.output, self.fixture)

    def test_rejects_unrelated_extra_contig(self) -> None:
        randomizer = random.Random(9)
        unrelated = "".join(randomizer.choices("ACGT", k=150))
        self.write_output(self.main, self.loop, unrelated)
        with self.assertRaisesRegex(RuntimeError, "contig 3 does not match"):
            self.check_assembly(self.output, self.fixture)

    def test_rejects_repetitive_contamination(self) -> None:
        randomizer = random.Random(42)
        long_main = "".join(randomizer.choices("ACGT", k=1000))
        write_fasta(self.fixture / "ref.fa", [long_main])
        self.write_output(long_main + "N" * 1000, self.loop)
        with self.assertRaisesRegex(RuntimeError, "contig 1 does not match"):
            self.check_assembly(self.output, self.fixture)

    def test_rejects_chimera_of_both_references(self) -> None:
        self.write_output(self.main + self.loop)
        with self.assertRaisesRegex(RuntimeError, "contig 1 does not match"):
            self.check_assembly(self.output, self.fixture)


if __name__ == "__main__":
    unittest.main()

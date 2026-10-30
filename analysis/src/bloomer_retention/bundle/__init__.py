"""Stage 3: the manuscript reporting bundle (SAP Part E).

The bundle computes nothing. It reads the four committed results JSONs in `outputs/` and rearranges them: it may
format, round, sort, concatenate and label, but it may not fit a model, run a test, or derive a statistic that the
analysis layer did not already write (SAP E1). Two code paths to one number is how a manuscript ends up disagreeing
with its own supplement, so a number no results JSON holds is a spec gap to be fixed in the analysis layer under a
SAP change, never a calculation here.

`tests/test_bundle_purity.py` enforces that rule by walking every module in this package with `ast`.
"""
from __future__ import annotations

EXIT_CODE = 6  # every bundle failure exits 6, and writes nothing (SAP E1)

__all__ = ["EXIT_CODE"]

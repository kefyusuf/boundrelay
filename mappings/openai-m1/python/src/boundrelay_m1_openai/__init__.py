"""BoundRelay P5 mapping: OpenAI Agents SDK (Python) x the M1 lesson.

Non-authoritative framework mapping per D-008. Reads only checked-in
artifacts (goprojection fixtures + M1 golden projections); emits the
SDK's native run-item stream; never feeds goldens, the failure matrix,
or the gates. The package name is boundrelay-m1-openai; the isolated
import name is boundrelay_m1_openai.
"""
from . import attribution, fixtures, mapping, results

__version__ = "0.0.0"

__all__ = [
    "attribution",
    "fixtures",
    "mapping",
    "results",
    "__version__",
]

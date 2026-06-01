"""Oracle — local machine-learning self-grading track record (Phase 20).

Every Apollo / Market / OSINT report has its checkable claims extracted, graded
against reality at 24h/7d/30d, and learned from (in-context lessons + a trained
scikit-learn calibrator). See :class:`OracleService`.
"""

from .calibrator import OracleCalibrator
from .grading import DEFAULT_HORIZONS_HOURS, FAILURE_TAGS, OUTCOMES
from .service import OracleService
from .store import OracleStore

__all__ = [
    "OracleService",
    "OracleStore",
    "OracleCalibrator",
    "FAILURE_TAGS",
    "OUTCOMES",
    "DEFAULT_HORIZONS_HOURS",
]

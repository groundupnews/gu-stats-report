"""Reporting periods.

The report covers one calendar month, given on the command line as YYYYMM
(e.g. 202501 for January 2025). It is compared with the month before and
with the same month a year earlier. This module knows how to work those out.
"""

import datetime
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Month:
    """A calendar month, e.g. Month(2025, 1) for January 2025."""

    year: int
    month: int

    @classmethod
    def parse(cls, text):
        """Turn 'YYYYMM' into a Month. Raises ValueError if it's malformed."""
        if not re.fullmatch(r"\d{6}", text):
            raise ValueError(f"'{text}' is not in the form YYYYMM, e.g. 202501")
        year, month = int(text[:4]), int(text[4:])
        if not 1 <= month <= 12:
            raise ValueError(f"'{text}' has month {month:02d}; it must be 01-12")
        return cls(year, month)

    def previous(self):
        """The month before this one (January -> December of the year before)."""
        if self.month == 1:
            return Month(self.year - 1, 12)
        return Month(self.year, self.month - 1)

    def year_earlier(self):
        """The same month one year earlier."""
        return Month(self.year - 1, self.month)

    @property
    def first_day(self):
        return datetime.date(self.year, self.month, 1)

    @property
    def matomo_date(self):
        """Matomo identifies a month by any date inside it; we use the 1st."""
        return self.first_day.isoformat()

    def has_finished(self, today=None):
        """True if the whole month is in the past."""
        today = today or datetime.date.today()
        return self.first_day < today.replace(day=1)

    def __str__(self):
        return self.first_day.strftime("%B %Y")  # e.g. "January 2025"

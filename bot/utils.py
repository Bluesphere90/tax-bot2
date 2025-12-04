# bot/utils.py
from datetime import datetime, date, timedelta
import pytz
import calendar
from typing import List, Tuple, Optional

# Hard-coded timezone per your decision
TZ = pytz.timezone("Asia/Bangkok")

def today_local_date() -> date:
    """Return current date in Asia/Bangkok timezone."""
    return datetime.now(TZ).date()

def is_weekend(d: date) -> bool:
    """Saturday/Sunday are weekends."""
    return d.weekday() >= 5  # 5 = Saturday, 6 = Sunday

def business_days_between(start: date, end: date, holidays: List[date]) -> int:
    """
    Count working days strictly after `start` up to and including `end`.
    (This matches the project's prior definition: exclusive start, inclusive end.)
    """
    if start >= end:
        # if same day: no days after start
        if start == end:
            return 0
        return 0
    cur = start + timedelta(days=1)
    cnt = 0
    while cur <= end:
        if (not is_weekend(cur)) and (cur not in (holidays or [])):
            cnt += 1
        cur += timedelta(days=1)
    return cnt

def business_day_before(deadline: date, n: int, holidays: List[date]) -> date:
    """
    Return the date D such that there are exactly n working days between D (exclusive) and deadline (inclusive).
    Example: if n==0 -> returns deadline itself.
    """
    if n <= 0:
        return deadline
    cur = deadline
    remaining = n
    while remaining > 0:
        cur = cur - timedelta(days=1)
        if (not is_weekend(cur)) and (cur not in (holidays or [])):
            remaining -= 1
    return cur

def last_day_of_month(y: int, m: int) -> date:
    last = calendar.monthrange(y, m)[1]
    return date(y, m, last)

def compute_deadline_for_requirement(freq: str, ref_date: date) -> Tuple[Optional[date], Optional[str]]:
    """
    Compute the next deadline date and canonical period string for a requirement frequency.
    freq: e.g. "monthly", "quarterly", "yearly"
    ref_date: reference date (usually today)
    Returns (deadline_date, period_string) or (None, None) if cannot compute.
    Period format:
      - monthly -> "MM/YYYY" (the month that is due)
      - quarterly -> "Qn/YYYY"
      - yearly -> "YYYY" (year that is due)
    Logic mirrors original project:
      - monthly deadlines on 20th of the month (deadline belongs to previous month period)
      - quarterly deadlines = last day of first month of next quarter; period is previous quarter
      - yearly deadlines = Mar 31 of next year for obligations of previous year
    """
    if not freq:
        return None, None
    f = (freq or "").lower()

    if f == "monthly":
        y = ref_date.year
        m = ref_date.month
        candidate = date(y, m, 20)
        if candidate < ref_date:
            # move to next month
            if m == 12:
                y += 1
                m = 1
            else:
                m += 1
            candidate = date(y, m, 20)
        # period is previous month of candidate
        p_month = candidate.month - 1
        p_year = candidate.year
        if p_month == 0:
            p_month = 12
            p_year -= 1
        period = f"{p_month:02d}/{p_year}"
        return candidate, period

    if f == "quarterly":
        y = ref_date.year
        m = ref_date.month
        current_q = (m - 1) // 3 + 1
        next_q = current_q + 1
        ny = y
        if next_q == 5:
            next_q = 1
            ny = y + 1
        first_month_next_q = (next_q - 1) * 3 + 1
        candidate = last_day_of_month(ny, first_month_next_q)
        if candidate < ref_date:
            # advance another quarter
            next_q += 1
            if next_q == 5:
                next_q = 1
                ny += 1
            first_month_next_q = (next_q - 1) * 3 + 1
            candidate = last_day_of_month(ny, first_month_next_q)
        # previous quarter number and year
        prev_q = ((first_month_next_q - 1) // 3)
        prev_qn = prev_q
        prev_year = ny
        if prev_qn == 0:
            prev_qn = 4
            prev_year -= 1
        period = f"Q{prev_qn}/{prev_year}"
        return candidate, period

    if f == "yearly":
        y = ref_date.year
        candidate = date(y + 1, 3, 31)
        if candidate < ref_date:
            candidate = date(y + 2, 3, 31)
        period = f"{candidate.year - 1}"
        return candidate, period

    return None, None

"""Salary cut for coming in late: a fixed amount for every full 5 minutes late, by salary slab.

Late minutes are counted per day from the employee's own shift start (or the office start time)
by the attendance router, so different start times are already handled there.
"""

BLOCK_MINUTES = 5

# (monthly salary up to and including, amount cut per 5 minutes late)
SLABS = [
    (20000, 50),
    (25000, 80),
    (30000, 100),
    (40000, 200),
]
ABOVE_TOP_SLAB = 250


def fine_per_block(salary: float) -> int:
    salary = float(salary or 0)
    for limit, amount in SLABS:
        if salary <= limit:
            return amount
    return ABOVE_TOP_SLAB


def late_blocks(late_minutes: int) -> int:
    """Full 5-minute blocks late on one day (e.g. 12 minutes -> 2)."""
    return max(0, int(late_minutes or 0)) // BLOCK_MINUTES


def late_deduction(salary: float, blocks: int) -> float:
    if not salary:
        return 0.0
    return float(blocks * fine_per_block(salary))


def salary_summary(salary: float, summary: dict) -> dict:
    """Monthly salary, the late cut so far and what remains, from a month_summary() result."""
    salary = float(salary or 0)
    cut = late_deduction(salary, summary.get("late_blocks", 0))
    return {
        "monthly_salary": round(salary, 2),
        "fine_per_5_min": fine_per_block(salary) if salary else 0,
        "late_minutes": summary.get("late_minutes", 0),
        "late_blocks": summary.get("late_blocks", 0),
        "late_deduction": round(cut, 2),
        "remaining": round(max(0.0, salary - cut), 2),
    }

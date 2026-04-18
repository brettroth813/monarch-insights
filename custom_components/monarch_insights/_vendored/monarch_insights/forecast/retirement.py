"""Monte Carlo FIRE / retirement simulator.

Pure-stdlib implementation (Box–Muller normals) so we don't require numpy. If numpy is
available we use it for a 50–100× speedup.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence


@dataclass
class FireOutcome:
    success: bool
    final_balance: float
    years_simulated: int
    path: list[float] = field(default_factory=list)


@dataclass
class MonteCarloResult:
    success_rate: float
    median_final: float
    p5_final: float
    p25_final: float
    p75_final: float
    p95_final: float
    safe_withdrawal_rate: float | None = None
    median_path: list[float] = field(default_factory=list)
    p5_path: list[float] = field(default_factory=list)
    p95_path: list[float] = field(default_factory=list)
    iterations: int = 0


class RetirementSimulator:
    def __init__(
        self,
        *,
        expected_real_return: float = 0.05,
        return_stdev: float = 0.15,
        inflation: float = 0.03,
        seed: int | None = None,
    ) -> None:
        self.expected_real_return = expected_real_return
        self.return_stdev = return_stdev
        self.inflation = inflation
        self.rng = random.Random(seed)

    def _draw_returns(self, n: int) -> Sequence[float]:
        try:
            import numpy as np  # type: ignore

            arr = np.random.default_rng(self.rng.randint(0, 2**31)).normal(
                self.expected_real_return, self.return_stdev, n
            )
            return arr.tolist()
        except ImportError:
            return [
                self.rng.gauss(self.expected_real_return, self.return_stdev) for _ in range(n)
            ]

    def simulate(
        self,
        starting_balance: float,
        annual_savings: float,
        years_to_retirement: int,
        annual_spend_in_retirement: float,
        years_in_retirement: int = 30,
        iterations: int = 1000,
    ) -> MonteCarloResult:
        total_years = years_to_retirement + years_in_retirement
        outcomes: list[FireOutcome] = []
        for _ in range(iterations):
            balance = starting_balance
            path = [balance]
            success = True
            returns = self._draw_returns(total_years)
            for year in range(total_years):
                r = returns[year]
                if year < years_to_retirement:
                    balance = balance * (1 + r) + annual_savings
                else:
                    balance = balance * (1 + r) - annual_spend_in_retirement
                path.append(balance)
                if balance <= 0:
                    success = False
                    break
            outcomes.append(
                FireOutcome(
                    success=success,
                    final_balance=path[-1] if path else 0,
                    years_simulated=len(path) - 1,
                    path=path,
                )
            )

        success_rate = sum(1 for o in outcomes if o.success) / iterations
        finals = sorted(o.final_balance for o in outcomes)
        median_final = _percentile(finals, 50)
        p5 = _percentile(finals, 5)
        p25 = _percentile(finals, 25)
        p75 = _percentile(finals, 75)
        p95 = _percentile(finals, 95)

        # Aggregate path percentiles year-by-year
        max_len = max(len(o.path) for o in outcomes)
        by_year: list[list[float]] = [[] for _ in range(max_len)]
        for o in outcomes:
            for i, v in enumerate(o.path):
                by_year[i].append(v)
        median_path = [_percentile(year_vals, 50) for year_vals in by_year]
        p5_path = [_percentile(year_vals, 5) for year_vals in by_year]
        p95_path = [_percentile(year_vals, 95) for year_vals in by_year]

        return MonteCarloResult(
            success_rate=success_rate,
            median_final=median_final,
            p5_final=p5,
            p25_final=p25,
            p75_final=p75,
            p95_final=p95,
            median_path=median_path,
            p5_path=p5_path,
            p95_path=p95_path,
            iterations=iterations,
        )

    def safe_withdrawal_rate(
        self,
        starting_balance: float,
        years_in_retirement: int = 30,
        target_success_rate: float = 0.95,
        iterations: int = 1000,
        precision: float = 0.0005,
    ) -> float:
        """Binary-search for the highest annual withdrawal that keeps success ≥ target."""
        lo, hi = 0.001, 0.10
        best = 0.0
        for _ in range(20):
            mid = (lo + hi) / 2
            result = self.simulate(
                starting_balance=starting_balance,
                annual_savings=0,
                years_to_retirement=0,
                annual_spend_in_retirement=starting_balance * mid,
                years_in_retirement=years_in_retirement,
                iterations=iterations,
            )
            if result.success_rate >= target_success_rate:
                best = mid
                lo = mid
            else:
                hi = mid
            if hi - lo < precision:
                break
        return best

    def fire_age(
        self,
        current_age: int,
        starting_balance: float,
        annual_savings: float,
        annual_spend_target: float,
        swr: float = 0.04,
        max_age: int = 80,
    ) -> int | None:
        fire_number = annual_spend_target / swr
        for years_out in range(max_age - current_age):
            result = self.simulate(
                starting_balance=starting_balance,
                annual_savings=annual_savings,
                years_to_retirement=years_out,
                annual_spend_in_retirement=annual_spend_target,
                years_in_retirement=30,
                iterations=300,
            )
            if result.median_final >= fire_number and result.success_rate >= 0.85:
                return current_age + years_out
        return None


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (pct / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)

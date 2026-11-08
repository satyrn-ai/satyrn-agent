import threading
import time

from plan_comparison.contracts import BudgetLimits, BudgetSnapshot


class BudgetExhausted(RuntimeError):
    pass


class MonotonicBudget:
    def __init__(self, limits: BudgetLimits) -> None:
        self._limits = limits
        self._started = time.monotonic()
        self._tokens = 0
        self._model_calls = 0
        self._lock = threading.Lock()

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            return BudgetSnapshot(
                elapsed_seconds=time.monotonic() - self._started,
                tokens=self._tokens,
                model_calls=self._model_calls,
            )

    def ensure_capacity(self) -> None:
        current = self.snapshot()
        if current.elapsed_seconds >= self._limits.wall_seconds:
            raise BudgetExhausted("Aggregate wall-time budget is exhausted.")
        if current.tokens >= self._limits.tokens:
            raise BudgetExhausted("Aggregate token budget is exhausted.")
        if current.model_calls >= self._limits.model_calls:
            raise BudgetExhausted("Aggregate model-call budget is exhausted.")

    def record_model_call(self) -> None:
        with self._lock:
            self._model_calls += 1
            if self._model_calls > self._limits.model_calls:
                raise BudgetExhausted(
                    "Worker exceeded the aggregate model-call budget."
                )

    def record_tokens(self, count: int) -> None:
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("Token usage must be a nonnegative integer.")
        with self._lock:
            self._tokens += count
            if self._tokens > self._limits.tokens:
                raise BudgetExhausted("Worker exceeded the aggregate token budget.")

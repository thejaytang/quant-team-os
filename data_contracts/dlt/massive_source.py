from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

try:
    import dlt
except Exception:  # pragma: no cover - local tests run without optional data stack
    dlt = None  # type: ignore[assignment]


RowLoader = Callable[[list[str], date, date, str], Iterable[dict[str, Any]]]


@dataclass(frozen=True)
class MassiveDltSource:
    symbols: list[str]
    start: date
    end: date
    frequency: str = "1d"

    def resource_name(self) -> str:
        return f"massive_ohlcv_{self.frequency}"

    def to_dlt_resource(self, row_loader: RowLoader):
        if dlt is None:
            raise RuntimeError("dlt is not installed")

        @dlt.resource(name=self.resource_name(), write_disposition="replace")
        def ohlcv_rows():
            yield from row_loader(self.symbols, self.start, self.end, self.frequency)

        return ohlcv_rows()

    def to_dlt_source(self, row_loader: RowLoader):
        if dlt is None:
            raise RuntimeError("dlt is not installed")
        resource = self.to_dlt_resource(row_loader)

        @dlt.source(name="massive")
        def massive_source():
            return resource

        return massive_source()

    def contract(self) -> dict[str, Any]:
        return {
            "tool": "dlt",
            "source": "massive",
            "resource": self.resource_name(),
            "symbols": self.symbols,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "frequency": self.frequency,
            "mode": "dlt_source" if dlt is not None else "contract_fallback",
        }


def build_source(symbols: list[str], start: date, end: date, frequency: str = "1d") -> MassiveDltSource:
    return MassiveDltSource(symbols=symbols, start=start, end=end, frequency=frequency)

"""Shared contracts. The authenticated server, never the model, chooses tenant identity."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any
from pydantic import BaseModel, Field, model_validator
class Scope(BaseModel):
    tenant_id: int = Field(ge=1, le=5)
    from_date: date
    to_date_exclusive: date
    timezone: str = "America/Lima"
    @model_validator(mode="after")
    def validate_window(self):
        ZoneInfo(self.timezone)
        if not 0 < (self.to_date_exclusive-self.from_date).days <= 800:
            raise ValueError("Date range must span between 1 and 800 days")
        return self
    def utc_bounds(self):
        zone = ZoneInfo(self.timezone)
        return tuple(datetime.combine(d, time.min, zone).astimezone(timezone.utc) for d in (self.from_date,self.to_date_exclusive))
class Evidence(BaseModel):
    query_id: str
    dataset_version: str
    effective_scope: Scope
    as_of: datetime
    event_watermark: datetime | None = None
    total_matching: int
    returned_rows: int
    truncated: bool = False
    rows: list[dict[str, Any]]
    aggregation_method: str = "exact"
    sources: list[str] = []
    warnings: list[str] = []

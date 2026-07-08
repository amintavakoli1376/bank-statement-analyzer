from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


def clean_number(value):
    """تبدیل رشته‌های عددی (با کاما، فاصله و ...) به float یا None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("٬", "").replace(" ", "").strip()
        if cleaned in ("", "-", "null", "None", "NaN"):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


class Transaction(BaseModel):
    date: str
    time: Optional[str] = None
    description: str = ""
    deposit: Optional[float] = 0
    withdrawal: Optional[float] = 0
    balance: Optional[float] = None
    source_page: int
    row_order: int

    @field_validator("deposit", "withdrawal", "balance", mode="before")
    @classmethod
    def _validate_numeric(cls, v):
        return clean_number(v)


class PageExtractionResult(BaseModel):
    page_number: int
    account_holder_name: Optional[str] = None
    transactions: List[Transaction] = Field(default_factory=list)
    extraction_status: str = "ok"  # ok | failed | skipped_empty
    notes: Optional[str] = None
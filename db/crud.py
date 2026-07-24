import json
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import AnalysisReport, Transaction


async def get_report_by_id(db: AsyncSession, report_id: int) -> AnalysisReport | None:
    result = await db.execute(
        select(AnalysisReport).where(AnalysisReport.id == report_id)
    )
    return result.scalar_one_or_none()


async def get_report_by_hash(db: AsyncSession, file_hash: str) -> AnalysisReport | None:
    result = await db.execute(
        select(AnalysisReport).where(AnalysisReport.file_hash == file_hash)
    )
    return result.scalar_one_or_none()


async def list_reports(db: AsyncSession, limit: int = 50, offset: int = 0) -> list[AnalysisReport]:
    result = await db.execute(
        select(AnalysisReport).order_by(AnalysisReport.id.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def get_transactions_df(db: AsyncSession, report_id: int) -> pd.DataFrame:
    """Load transactions for a report as a DataFrame."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.analysis_report_id == report_id)
        .order_by(Transaction.row_order)
    )
    rows = result.scalars().all()
    if not rows:
        return pd.DataFrame()
    records = [
        {
            "date": r.date, "time": r.time, "description": r.description,
            "deposit": r.deposit, "withdrawal": r.withdrawal,
            "balance": r.balance, "source_page": r.source_page,
        }
        for r in rows
    ]
    return pd.DataFrame(records)


async def create_report(
    db: AsyncSession,
    file_hash: str,
    original_filename: str,
    account_holder_name: str | None = None,
    account_type: str | None = None,
    features: dict | None = None,
    report: dict | None = None,
    status: str = "completed",
    error_message: str | None = None,
) -> AnalysisReport:
    rpt = AnalysisReport(
        file_hash=file_hash,
        original_filename=original_filename,
        account_holder_name=account_holder_name,
        account_type=account_type,
        features_json=json.dumps(features, ensure_ascii=False, default=str) if features else None,
        report_json=json.dumps(report, ensure_ascii=False, default=str) if report else None,
        status=status,
        error_message=error_message,
    )
    db.add(rpt)
    await db.commit()
    await db.refresh(rpt)
    return rpt


async def get_transactions_by_report_id(db: AsyncSession, report_id: int) -> list[dict]:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.analysis_report_id == report_id)
        .order_by(Transaction.row_order)
    )
    rows = result.scalars().all()
    return [
        {
            "date": r.date, "time": r.time, "description": r.description,
            "deposit": r.deposit, "withdrawal": r.withdrawal,
            "balance": r.balance, "source_page": r.source_page,
        }
        for r in rows
    ]


async def save_transactions_bulk(
    db: AsyncSession, report_id: int, transactions: list[dict]
) -> int:
    """Insert transactions in bulk. Returns count inserted."""
    if not transactions:
        return 0
    objs = [Transaction(analysis_report_id=report_id, **t) for t in transactions]
    db.add_all(objs)
    await db.commit()
    return len(objs)


async def update_report_status(
    db: AsyncSession, report_id: int, status: str, error_message: str | None = None
):
    from sqlalchemy import update
    await db.execute(
        update(AnalysisReport)
        .where(AnalysisReport.id == report_id)
        .values(status=status, error_message=error_message)
    )
    await db.commit()

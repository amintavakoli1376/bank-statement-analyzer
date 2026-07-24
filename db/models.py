from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Index
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    file_hash = Column(String, unique=True, nullable=False)
    original_filename = Column(String, nullable=False)
    account_holder_name = Column(String, nullable=True)
    account_type = Column(String, nullable=True)  # BUSINESS/SALARIED/PERSONAL
    extracted_at = Column(DateTime, default=datetime.utcnow)
    features_json = Column(Text, nullable=True)  # JSONB via Text (asyncpg handles JSON)
    report_json = Column(Text, nullable=True)
    status = Column(String, default="completed")  # completed/failed
    error_message = Column(String, nullable=True)

    __table_args__ = (Index("ix_analysis_reports_file_hash", "file_hash"),)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_report_id = Column(Integer, ForeignKey("analysis_reports.id"), nullable=False)
    date = Column(String, nullable=False)
    time = Column(String, nullable=True)
    description = Column(Text, default="")
    deposit = Column(Float, nullable=True)
    withdrawal = Column(Float, nullable=True)
    balance = Column(Float, nullable=True)
    source_page = Column(Integer, nullable=False)
    row_order = Column(Integer, nullable=False)

    __table_args__ = (Index("ix_transactions_report_id", "analysis_report_id"),)

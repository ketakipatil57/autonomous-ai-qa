"""SQLAlchemy 2.x ORM models according to Section 7 of specification."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


def utc_now() -> datetime:
    """Return current UTC timestamp without timezone offset issues."""
    return datetime.now(timezone.utc)


class TestSession(Base):
    """Execution session storing run configuration, progress stages, and metrics."""

    __test__ = False
    __tablename__ = "test_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    app_url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    branch: Mapped[str] = mapped_column(String(20), nullable=False)  # "instruction" | "exploration"
    planner_source: Mapped[str] = mapped_column(String(20), default="fallback")  # "openai" | "fallback"
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")  # QUEUED|RUNNING|COMPLETED|FAILED_TO_RUN

    # Progress tracking (Section 9)
    stage: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # exploring|planning|executing|rechecking|reporting|done
    current_step: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tests_done: Mapped[int] = mapped_column(Integer, default=0)
    tests_total: Mapped[int] = mapped_column(Integer, default=0)

    # Metric counts (Section 7)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_review_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    test_cases: Mapped[List[TestCaseModel]] = relationship(
        "TestCaseModel", back_populates="session", cascade="all, delete-orphan"
    )
    test_results: Mapped[List[TestResultModel]] = relationship(
        "TestResultModel", back_populates="session", cascade="all, delete-orphan"
    )
    bug_reports: Mapped[List[BugReportModel]] = relationship(
        "BugReportModel", back_populates="session", cascade="all, delete-orphan"
    )


class TestCaseModel(Base):
    """Individual planned test case associated with a session."""

    __test__ = False
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_sessions.id", ondelete="CASCADE"), nullable=False)
    tc_code: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "TC-01"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # functional|validation|edge|negative
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-serialized list[Action]
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    related_bug_hint: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    # Relationships
    session: Mapped[TestSession] = relationship("TestSession", back_populates="test_cases")
    results: Mapped[List[TestResultModel]] = relationship("TestResultModel", back_populates="test_case")


class TestResultModel(Base):
    """Verified test outcome and recheck result for a test case."""

    __test__ = False
    __tablename__ = "test_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_sessions.id", ondelete="CASCADE"), nullable=False)
    test_case_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # PASSED | FAILED | NEEDS_REVIEW
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    first_run_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    recheck_outcome: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    failure_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    evidence_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    report_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    # Relationships
    session: Mapped[TestSession] = relationship("TestSession", back_populates="test_results")
    test_case: Mapped[TestCaseModel] = relationship("TestCaseModel", back_populates="results")
    evidence_records: Mapped[List[EvidenceModel]] = relationship(
        "EvidenceModel", back_populates="test_result", cascade="all, delete-orphan"
    )
    bug_reports: Mapped[List[BugReportModel]] = relationship("BugReportModel", back_populates="test_result")


class BugReportModel(Base):
    """Confirmed bug report generated from a verified FAILED test."""

    __tablename__ = "bug_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_sessions.id", ondelete="CASCADE"), nullable=False)
    test_result_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False)
    bug_code: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. BUG-abc12345-1
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # LOW | MEDIUM | HIGH
    reproduction_steps_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actual: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    # Relationships
    session: Mapped[TestSession] = relationship("TestSession", back_populates="bug_reports")
    test_result: Mapped[TestResultModel] = relationship("TestResultModel", back_populates="bug_reports")


class EvidenceModel(Base):
    """Structured evidence record linked to a test result."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    test_result_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # screenshot | console | network | pytest
    path_or_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    # Relationships
    test_result: Mapped[TestResultModel] = relationship("TestResultModel", back_populates="evidence_records")


class RegressionTestModel(Base):
    """Saved passed test case for regression suite replay."""

    __tablename__ = "regression_tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    source_session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    test_case_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tc_code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="functional")
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # PASSED|FAILED|NEEDS_REVIEW
    run_count: Mapped[int] = mapped_column(Integer, default=1)

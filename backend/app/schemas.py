"""Pydantic v2 schemas for API requests and responses according to Section 9."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class RunRequest(BaseModel):
    """Payload to create and launch a new testing session."""

    app_url: str = Field(..., description="Target application URL to test")
    description: Optional[str] = Field(None, description="Optional description of application")
    instruction: Optional[str] = Field(None, description="Optional specific user instruction (Branch A)")
    max_tests: int = Field(8, ge=1, le=8, description="Maximum test cases to generate (max 8)")

    @field_validator("app_url")
    @classmethod
    def validate_app_url(cls, v: str) -> str:
        s = v.strip()
        if not s.startswith(("http://", "https://")):
            s = "http://" + s
        return s


class SessionCounts(BaseModel):
    """Aggregate counts for a testing session."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    needs_review: int = 0


class SessionResponse(BaseModel):
    """Summary of a testing session."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    app_url: str
    description: Optional[str] = None
    instruction: Optional[str] = None
    branch: str
    planner_source: str
    status: str
    stage: Optional[str] = None
    current_step: Optional[str] = None
    tests_done: int = 0
    tests_total: int = 0
    total_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    needs_review_count: int = 0
    created_at: datetime
    completed_at: Optional[datetime] = None


class SessionDetailResponse(SessionResponse):
    """Detailed session model including progress and counts mapping."""

    counts: SessionCounts = Field(default_factory=SessionCounts)


class TestResultResponse(BaseModel):
    """Summary of an individual test case result."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    test_case_id: str
    tc_code: str
    title: str
    category: str
    status: str  # PASSED | FAILED | NEEDS_REVIEW
    reason: str
    first_run_outcome: str
    recheck_outcome: Optional[str] = None
    duration_ms: float = 0.0
    failure_message: Optional[str] = None
    explanation: Optional[str] = None
    screenshot_url: Optional[str] = None
    report_url: Optional[str] = None


class TestResultDetailResponse(TestResultResponse):
    """Comprehensive test case result with all attached evidence."""

    steps: List[dict[str, Any]] = Field(default_factory=list)
    expected: Optional[str] = None
    console_logs: List[dict[str, Any]] = Field(default_factory=list)
    network_errors: List[dict[str, Any]] = Field(default_factory=list)
    final_url: Optional[str] = None


class BugReportResponse(BaseModel):
    """Confirmed bug report summary."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    test_result_id: str
    bug_code: str
    title: str
    severity: str
    reproduction_steps: List[str] = Field(default_factory=list)
    expected: Optional[str] = None
    actual: Optional[str] = None
    report_url: Optional[str] = None
    created_at: datetime


class RegressionTestResponse(BaseModel):
    """Saved regression test case."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_session_id: str
    test_case_id: str
    tc_code: str
    title: str
    category: str
    steps: List[dict[str, Any]] = Field(default_factory=list)
    expected: str
    created_at: datetime
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    run_count: int = 1


class RegressionRunResponse(BaseModel):
    """Response returned when initiating a regression suite run."""

    session_id: str
    test_count: int
    message: str

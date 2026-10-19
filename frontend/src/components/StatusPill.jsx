import React from 'react';

export default function StatusPill({ status }) {
  const normStatus = (status || 'UNKNOWN').toUpperCase();
  let className = 'status-queued';

  if (normStatus === 'PASSED') {
    className = 'status-passed';
  } else if (normStatus === 'FAILED') {
    className = 'status-failed';
  } else if (normStatus === 'NEEDS_REVIEW' || normStatus === 'NEEDS-REVIEW') {
    className = 'status-needs_review';
  } else if (normStatus === 'RUNNING') {
    className = 'status-running';
  } else if (normStatus === 'COMPLETED') {
    className = 'status-completed';
  }

  const label = normStatus === 'NEEDS_REVIEW' ? 'Needs Review' : normStatus;

  return <span className={`status-pill ${className}`}>{label}</span>;
}

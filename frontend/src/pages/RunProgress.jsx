import React, { useEffect, useState } from 'react';
import { getSession, getSessionResults } from '../api';
import StatusPill from '../components/StatusPill';

const STAGES = ['exploring', 'planning', 'executing', 'rechecking', 'reporting', 'done'];

export default function RunProgress({ sessionId, onViewResults }) {
  const [session, setSession] = useState(null);
  const [results, setResults] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!sessionId) return;

    let isMounted = true;

    const fetchProgress = async () => {
      try {
        const s = await getSession(sessionId);
        if (isMounted) {
          setSession(s);
          setError(null);
        }

        // Also fetch live finished results
        const resList = await getSessionResults(sessionId);
        if (isMounted) {
          setResults(resList);
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message || 'Failed to poll session progress.');
        }
      }
    };

    // Immediate first fetch
    fetchProgress();

    // Poll every 2 seconds
    const intervalId = setInterval(fetchProgress, 2000);

    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, [sessionId]);

  if (!sessionId) {
    return (
      <div className="card">
        <p>No active test run selected. Please launch a run from the New Run page.</p>
      </div>
    );
  }

  const currentStage = (session?.stage || 'planning').toLowerCase();
  const currentStageIndex = STAGES.indexOf(currentStage);
  const isFinished = session?.status === 'COMPLETED' || session?.status === 'FAILED_TO_RUN';

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h2 className="card-title">Live Execution Progress</h2>
            <p className="card-subtitle">
              Session ID: <code>{sessionId}</code> | Branch: <strong>{session?.branch || 'N/A'}</strong> | Planner: <strong>{session?.planner_source || 'fallback'}</strong>
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <StatusPill status={session?.status || 'QUEUED'} />
            {isFinished && (
              <button className="btn-primary" onClick={onViewResults}>
                View Full Results →
              </button>
            )}
          </div>
        </div>

        {error && (
          <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', padding: '0.75rem 1rem', borderRadius: '6px', color: '#b91c1c', marginBottom: '1rem' }}>
            {error}
          </div>
        )}

        {/* Stage Stepper */}
        <div className="stepper">
          {STAGES.map((stg, idx) => {
            const isCompleted = isFinished || (currentStageIndex > -1 && idx < currentStageIndex);
            const isActive = !isFinished && idx === currentStageIndex;
            let statusClass = '';
            if (isCompleted) statusClass = 'completed';
            else if (isActive) statusClass = 'active';

            return (
              <div key={stg} className={`step-item ${statusClass}`}>
                <div className="step-circle">
                  {isCompleted ? '✓' : idx + 1}
                </div>
                <span className="step-label">
                  {stg.charAt(0).toUpperCase() + stg.slice(1)}
                </span>
              </div>
            );
          })}
        </div>

        {/* Live Step Box */}
        <div className={`live-progress-box ${session?.status === 'RUNNING' ? 'running' : ''}`}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            {session?.status === 'RUNNING' && <span className="spinner"></span>}
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                {session?.current_step || 'Initializing...'}
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                {session?.tests_total > 0
                  ? `${session.tests_done || 0} of ${session.tests_total} tests complete`
                  : 'Preparing test plan...'}
              </div>
            </div>
          </div>

          {session?.counts && (
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--passed)', fontWeight: 600 }}>
                {session.counts.passed} Passed
              </span>
              <span>•</span>
              <span style={{ fontSize: '0.85rem', color: 'var(--failed)', fontWeight: 600 }}>
                {session.counts.failed} Failed
              </span>
              <span>•</span>
              <span style={{ fontSize: '0.85rem', color: 'var(--review)', fontWeight: 600 }}>
                {session.counts.needs_review} Needs Review
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Live Finished Tests Table */}
      <div className="card">
        <h3 className="card-title" style={{ fontSize: '1.1rem' }}>
          Completed Test Cases ({results.length})
        </h3>
        {results.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            Waiting for tests to finish executing...
          </p>
        ) : (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Test ID</th>
                  <th>Title</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.tc_code}</strong></td>
                    <td>{r.title}</td>
                    <td style={{ textTransform: 'capitalize' }}>{r.category}</td>
                    <td><StatusPill status={r.status} /></td>
                    <td>{r.duration_ms ? `${r.duration_ms} ms` : '—'}</td>
                    <td style={{ maxWidth: '300px', fontSize: '0.85rem' }}>{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

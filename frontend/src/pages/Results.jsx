import React, { useEffect, useState } from 'react';
import { getSession, getSessionResults, runRegression } from '../api';
import StatusPill from '../components/StatusPill';

export default function Results({ sessionId, onSelectResult, onRegressionStarted }) {
  const [session, setSession] = useState(null);
  const [results, setResults] = useState([]);
  const [filter, setFilter] = useState('ALL');
  const [loading, setLoading] = useState(true);
  const [rerunLoading, setRerunLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!sessionId) return;

    const loadData = async () => {
      try {
        setLoading(true);
        const s = await getSession(sessionId);
        setSession(s);

        const resList = await getSessionResults(sessionId);
        setResults(resList);
        setError(null);
      } catch (err) {
        setError(err.message || 'Failed to load session results.');
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [sessionId]);

  const handleRerunRegression = async () => {
    try {
      setRerunLoading(true);
      const newSession = await runRegression();
      if (onRegressionStarted) {
        onRegressionStarted(newSession.id);
      }
    } catch (err) {
      alert(`Failed to rerun regression: ${err.message}`);
    } finally {
      setRerunLoading(false);
    }
  };

  const filteredResults = results.filter((r) => {
    if (filter === 'ALL') return true;
    return r.status === filter;
  });

  const passedCount = session?.passed_count ?? results.filter((r) => r.status === 'PASSED').length;
  const failedCount = session?.failed_count ?? results.filter((r) => r.status === 'FAILED').length;
  const reviewCount = session?.needs_review_count ?? results.filter((r) => r.status === 'NEEDS_REVIEW').length;
  const totalCount = results.length;

  return (
    <div>
      {/* Summary Cards */}
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-value">{totalCount}</div>
          <div className="metric-label">Total Tests</div>
        </div>
        <div className="metric-card metric-passed">
          <div className="metric-value">{passedCount}</div>
          <div className="metric-label">Passed</div>
        </div>
        <div className="metric-card metric-failed">
          <div className="metric-value">{failedCount}</div>
          <div className="metric-label">Confirmed Bugs</div>
        </div>
        <div className="metric-card metric-review">
          <div className="metric-value">{reviewCount}</div>
          <div className="metric-label">Needs Review</div>
        </div>
      </div>

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h2 className="card-title">Session Test Results</h2>
            <p className="card-subtitle" style={{ marginBottom: 0 }}>
              Session: <code>{sessionId}</code> | Target: {session?.app_url}
            </p>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <button
              className="btn-secondary"
              onClick={handleRerunRegression}
              disabled={rerunLoading || passedCount === 0}
              title={passedCount === 0 ? 'No passed tests available to rerun' : 'Rerun verified passing tests'}
            >
              {rerunLoading ? 'Launching...' : '↻ Rerun as Regression'}
            </button>
          </div>
        </div>

        {error && (
          <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', padding: '0.75rem', borderRadius: '6px', color: '#b91c1c', marginBottom: '1rem' }}>
            {error}
          </div>
        )}

        {/* Status Filters */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem' }}>
          {['ALL', 'PASSED', 'FAILED', 'NEEDS_REVIEW'].map((st) => (
            <button
              key={st}
              className={`nav-btn ${filter === st ? 'active' : ''}`}
              onClick={() => setFilter(st)}
              style={{ fontSize: '0.85rem', padding: '0.35rem 0.75rem' }}
            >
              {st === 'ALL' ? 'All Results' : st === 'NEEDS_REVIEW' ? 'Needs Review' : st}
            </button>
          ))}
        </div>

        {/* Results Table */}
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Test ID</th>
                <th>Title</th>
                <th>Category</th>
                <th>Status</th>
                <th>Reason</th>
                <th>Duration</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredResults.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                    No results matching the selected filter.
                  </td>
                </tr>
              ) : (
                filteredResults.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.tc_code}</strong></td>
                    <td>{r.title}</td>
                    <td style={{ textTransform: 'capitalize' }}>{r.category}</td>
                    <td><StatusPill status={r.status} /></td>
                    <td style={{ maxWidth: '320px', fontSize: '0.85rem' }}>{r.reason}</td>
                    <td>{r.duration_ms ? `${r.duration_ms} ms` : '—'}</td>
                    <td>
                      <button
                        className="btn-secondary"
                        style={{ padding: '0.35rem 0.65rem', fontSize: '0.8rem' }}
                        onClick={() => onSelectResult(r.id)}
                      >
                        {r.status === 'FAILED' ? 'View Bug →' : 'View Detail →'}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

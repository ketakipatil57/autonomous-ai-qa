import React, { useEffect, useState } from 'react';
import { getBugReportUrl, getResultDetail } from '../api';
import StatusPill from '../components/StatusPill';

export default function BugDetail({ resultId, onBack }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!resultId) return;

    const loadDetail = async () => {
      try {
        setLoading(true);
        const data = await getResultDetail(resultId);
        setDetail(data);
        setError(null);
      } catch (err) {
        setError(err.message || 'Failed to load test result detail.');
      } finally {
        setLoading(false);
      }
    };

    loadDetail();
  }, [resultId]);

  if (loading) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
        <span className="spinner" style={{ width: '28px', height: '28px', marginBottom: '1rem' }}></span>
        <p>Loading bug and execution evidence...</p>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="card">
        <p style={{ color: 'var(--failed)' }}>Error: {error || 'Result detail not found.'}</p>
        <button className="btn-secondary" onClick={onBack} style={{ marginTop: '1rem' }}>
          ← Back to Results
        </button>
      </div>
    );
  }

  const isBug = detail.status === 'FAILED';
  const htmlReportUrl = getBugReportUrl(detail.id);

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.5rem' }}>
              <StatusPill status={detail.status} />
              <span className="branch-pill" style={{ textTransform: 'capitalize' }}>
                Category: <strong>{detail.category}</strong>
              </span>
              <span className="branch-pill">
                Duration: <strong>{detail.duration_ms} ms</strong>
              </span>
            </div>
            <h2 className="card-title" style={{ fontSize: '1.4rem' }}>
              {detail.tc_code}: {detail.title}
            </h2>
            <p className="card-subtitle" style={{ marginBottom: 0 }}>
              Session: <code>{detail.session_id}</code> | First Run: <strong>{detail.first_run_outcome}</strong>
              {detail.recheck_outcome && ` | Recheck: ${detail.recheck_outcome}`}
            </p>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {isBug && (
              <a
                href={htmlReportUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-primary"
                style={{ fontSize: '0.85rem' }}
              >
                Open Full HTML Report ↗
              </a>
            )}
            <button className="btn-secondary" onClick={onBack} style={{ fontSize: '0.85rem' }}>
              ← Back to Results
            </button>
          </div>
        </div>

        {/* Reason / Explanation */}
        <div style={{ background: '#f8fafc', border: '1px solid var(--border)', borderRadius: '8px', padding: '1rem', marginBottom: '1.5rem' }}>
          <strong style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.25rem' }}>
            Agent Diagnosis & Explanation:
          </strong>
          <p style={{ fontSize: '0.95rem', color: 'var(--text)' }}>
            {detail.explanation || detail.reason || 'No diagnostic explanation recorded.'}
          </p>
        </div>

        {/* Expected vs Actual Side-by-Side */}
        <div className="compare-grid">
          <div className="compare-box expected">
            <h3 style={{ fontSize: '1rem', color: 'var(--passed)', marginBottom: '0.5rem' }}>
              ✓ Expected Behavior
            </h3>
            <p style={{ fontSize: '0.95rem' }}>
              {detail.expected || 'Requirement defined in test specification.'}
            </p>
          </div>

          <div className="compare-box actual">
            <h3 style={{ fontSize: '1rem', color: 'var(--failed)', marginBottom: '0.5rem' }}>
              ✗ Observed Actual Behavior
            </h3>
            <p style={{ fontSize: '0.95rem' }}>
              {detail.failure_message || detail.reason || 'Application state diverged from expected outcome.'}
            </p>
          </div>
        </div>

        {/* Numbered Reproduction Steps */}
        <div style={{ marginBottom: '1.5rem' }}>
          <h3 className="card-title" style={{ fontSize: '1.1rem' }}>Reproduction Steps</h3>
          {detail.steps && detail.steps.length > 0 ? (
            <ol className="repro-list">
              {detail.steps.map((st, i) => (
                <li key={i}>
                  <strong>{st.type}</strong> {st.target ? `target: "${st.target}"` : ''} {st.value ? `value: "${st.value}"` : ''}
                </li>
              ))}
            </ol>
          ) : (
            <p style={{ color: 'var(--text-muted)' }}>No individual steps recorded for this test.</p>
          )}
        </div>

        {/* Evidence Artifacts */}
        <div>
          <h3 className="card-title" style={{ fontSize: '1.1rem', marginBottom: '0.75rem' }}>
            Attached Evidence
          </h3>

          {/* Failure Screenshot */}
          {detail.screenshot_url && (
            <div className="evidence-section">
              <strong style={{ fontSize: '0.9rem' }}>Page Screenshot at Point of Failure:</strong>
              <div style={{ marginTop: '0.5rem' }}>
                <img
                  src={detail.screenshot_url}
                  alt={`Failure screenshot for ${detail.tc_code}`}
                  className="screenshot-img"
                />
              </div>
            </div>
          )}

          {/* Console Errors */}
          <div className="evidence-section">
            <strong style={{ fontSize: '0.9rem' }}>
              Browser Console Errors ({detail.console_logs?.length || 0}):
            </strong>
            {detail.console_logs && detail.console_logs.length > 0 ? (
              <div style={{ marginTop: '0.5rem' }}>
                {detail.console_logs.map((c, i) => (
                  <div key={i} className="code-block" style={{ marginBottom: '0.4rem', color: c.type === 'error' ? '#f87171' : '#fbbf24' }}>
                    [{c.type.toUpperCase()}] {c.text} {c.location && `(${c.location})`}
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '0.35rem' }}>
                No console errors or warnings were logged by the browser.
              </p>
            )}
          </div>

          {/* Network Errors */}
          <div className="evidence-section">
            <strong style={{ fontSize: '0.9rem' }}>
              Failed Network Requests / HTTP 4xx & 5xx ({detail.network_errors?.length || 0}):
            </strong>
            {detail.network_errors && detail.network_errors.length > 0 ? (
              <div style={{ marginTop: '0.5rem' }}>
                {detail.network_errors.map((n, i) => (
                  <div key={i} className="code-block" style={{ marginBottom: '0.4rem', color: '#f87171' }}>
                    {n.method} {n.url} - {n.status ? `Status ${n.status}` : n.failure || 'Failed'}
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '0.35rem' }}>
                No failed network requests or HTTP 4xx/5xx responses recorded.
              </p>
            )}
          </div>

          {/* Pytest Assertion Failure Excerpt */}
          {detail.failure_message && (
            <div className="evidence-section">
              <strong style={{ fontSize: '0.9rem' }}>Pytest Assertion Failure Excerpt:</strong>
              <div className="code-block" style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap' }}>
                {detail.failure_message}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

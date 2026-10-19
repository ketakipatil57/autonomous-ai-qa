import React, { useEffect, useState } from 'react';
import { listRegressionTests, runRegression } from '../api';
import StatusPill from '../components/StatusPill';

export default function Regression({ onRegressionStarted }) {
  const [tests, setTests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  const loadTests = async () => {
    try {
      setLoading(true);
      const data = await listRegressionTests();
      setTests(data);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to load regression suite.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTests();
  }, []);

  const handleRunAll = async () => {
    try {
      setRunning(true);
      const newSession = await runRegression();
      if (onRegressionStarted) {
        onRegressionStarted(newSession.id);
      }
    } catch (err) {
      alert(`Failed to start regression suite: ${err.message}`);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 className="card-title">Saved Regression Test Suite</h2>
          <p className="card-subtitle" style={{ marginBottom: 0 }}>
            Verified passing user journeys are automatically stored here for continuous regression testing.
          </p>
        </div>

        <button
          className="btn-primary"
          onClick={handleRunAll}
          disabled={running || tests.length === 0}
          title={tests.length === 0 ? 'No regression tests saved yet' : 'Rerun all saved regression tests'}
        >
          {running ? 'Launching Rerun...' : `Run Regression Suite (${tests.length})`}
        </button>
      </div>

      {error && (
        <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', padding: '0.75rem', borderRadius: '6px', color: '#b91c1c', marginBottom: '1rem' }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '2rem' }}>
          <span className="spinner"></span>
          <p style={{ marginTop: '0.5rem', color: 'var(--text-muted)' }}>Loading saved regression tests...</p>
        </div>
      ) : tests.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '3rem 1rem', border: '1px dashed var(--border)', borderRadius: '8px' }}>
          <p style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.5rem' }}>No Regression Tests Saved Yet</p>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', maxWidth: '500px', margin: '0 auto' }}>
            Run tests against your application. Any test cases that pass on the first run will be automatically saved here for one-click regression replay.
          </p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Test ID</th>
                <th>Title</th>
                <th>Category</th>
                <th>Expected Outcome</th>
                <th>Run Count</th>
                <th>Last Status</th>
                <th>Saved On</th>
              </tr>
            </thead>
            <tbody>
              {tests.map((t) => (
                <tr key={t.id}>
                  <td><strong>{t.tc_code}</strong></td>
                  <td>{t.title}</td>
                  <td style={{ textTransform: 'capitalize' }}>{t.category}</td>
                  <td style={{ maxWidth: '300px', fontSize: '0.85rem' }}>{t.expected}</td>
                  <td><strong>{t.run_count}</strong></td>
                  <td><StatusPill status={t.last_status || 'PASSED'} /></td>
                  <td style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                    {t.created_at ? new Date(t.created_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

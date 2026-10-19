import React, { useState } from 'react';
import { createSession, startSession } from '../api';

export default function NewRun({ onRunStarted }) {
  const [appUrl, setAppUrl] = useState('http://localhost:3000');
  const [description, setDescription] = useState('E-commerce store with catalog, login, cart, and checkout.');
  const [instruction, setInstruction] = useState('');
  const [maxTests, setMaxTests] = useState(8);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    let cleanUrl = appUrl.trim();
    if (!cleanUrl) {
      setError('Application URL is required.');
      return;
    }

    if (!cleanUrl.startsWith('http://') && !cleanUrl.startsWith('https://')) {
      cleanUrl = 'http://' + cleanUrl;
    }

    try {
      setLoading(true);
      // 1. Create session (QUEUED)
      const session = await createSession({
        app_url: cleanUrl,
        description: description.trim() || null,
        instruction: instruction.trim() || null,
        max_tests: Number(maxTests) || 8,
      });

      // 2. Start session (RUNNING)
      await startSession(session.id);

      // 3. Callback to parent to transition to RunProgress page
      onRunStarted(session.id);
    } catch (err) {
      setError(err.message || 'Failed to start test session.');
    } finally {
      setLoading(false);
    }
  };

  const isBranchA = Boolean(instruction.trim());

  return (
    <div className="card">
      <h2 className="card-title">Launch Autonomous Test Run</h2>
      <p className="card-subtitle">
        Configure application URL and optional test instructions. The AI agent will plan, execute,
        verify, and collect failure evidence.
      </p>

      {error && (
        <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', padding: '0.75rem 1rem', borderRadius: '6px', color: '#b91c1c', marginBottom: '1.25rem' }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label className="form-label" htmlFor="appUrl">Application URL *</label>
          <input
            id="appUrl"
            type="text"
            className="form-input"
            value={appUrl}
            onChange={(e) => setAppUrl(e.target.value)}
            placeholder="http://localhost:3000"
            required
          />
          <div className="form-hint">Must belong to domain allowlist (e.g. localhost, 127.0.0.1).</div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="instruction">Specific Test Instruction (Optional)</label>
          <textarea
            id="instruction"
            className="form-textarea"
            rows={3}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="e.g. Test login with a wrong password or Verify checkout total with quantity 2"
          />
          <div className="form-hint">
            <strong>Hint:</strong> Leave the instruction empty to let the agent explore the app.
          </div>
        </div>

        <div className="branch-pills">
          <div className="branch-pill" style={{ borderColor: isBranchA ? '#3b82f6' : 'var(--border)', background: isBranchA ? '#eff6ff' : 'var(--bg)' }}>
            <strong>{isBranchA ? '● Branch A Active:' : '○ Branch A:'}</strong> Direct test generation from specific instruction
          </div>
          <div className="branch-pill" style={{ borderColor: !isBranchA ? '#3b82f6' : 'var(--border)', background: !isBranchA ? '#eff6ff' : 'var(--bg)' }}>
            <strong>{!isBranchA ? '● Branch B Active:' : '○ Branch B:'}</strong> Autonomous Playwright crawl & exploration of key journeys
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="description">Application Description (Optional)</label>
          <textarea
            id="description"
            className="form-textarea"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional context to help the planner generate relevant test assertions"
          />
        </div>

        <div className="form-group" style={{ maxWidth: '200px' }}>
          <label className="form-label" htmlFor="maxTests">Maximum Tests (1–8)</label>
          <input
            id="maxTests"
            type="number"
            min={1}
            max={8}
            className="form-input"
            value={maxTests}
            onChange={(e) => setMaxTests(e.target.value)}
          />
        </div>

        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? (
            <>
              <span className="spinner"></span> Starting Agent Pipeline...
            </>
          ) : (
            'Run Tests'
          )}
        </button>
      </form>
    </div>
  );
}

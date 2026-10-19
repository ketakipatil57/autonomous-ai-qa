import React from 'react';

export default function Dashboard({ currentTab, onSelectTab, activeSessionId }) {
  return (
    <header className="header">
      <div className="logo-area">
        <span className="logo-icon">🧪</span>
        <div>
          <h1 className="logo-title">Autonomous AI QA Engineer</h1>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            VIT Code_Apex 3.0 | iMocha Track 2
          </p>
        </div>
      </div>

      <nav className="nav-links">
        <button
          className={`nav-btn ${currentTab === 'new' ? 'active' : ''}`}
          onClick={() => onSelectTab('new')}
        >
          New Run
        </button>

        <button
          className={`nav-btn ${currentTab === 'progress' ? 'active' : ''}`}
          onClick={() => onSelectTab('progress')}
          disabled={!activeSessionId}
          title={!activeSessionId ? 'Start a run first' : 'View active run progress'}
        >
          Run Progress
        </button>

        <button
          className={`nav-btn ${currentTab === 'results' ? 'active' : ''}`}
          onClick={() => onSelectTab('results')}
          disabled={!activeSessionId}
          title={!activeSessionId ? 'Run tests to view results' : 'View session results'}
        >
          Results
        </button>

        <button
          className={`nav-btn ${currentTab === 'regression' ? 'active' : ''}`}
          onClick={() => onSelectTab('regression')}
        >
          Regression Suite
        </button>
      </nav>
    </header>
  );
}

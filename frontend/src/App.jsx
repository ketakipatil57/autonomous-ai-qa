import React, { useState } from 'react';
import Dashboard from './components/Dashboard';
import NewRun from './pages/NewRun';
import RunProgress from './pages/RunProgress';
import Results from './pages/Results';
import BugDetail from './pages/BugDetail';
import Regression from './pages/Regression';

export default function App() {
  const [currentTab, setCurrentTab] = useState('new');
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [selectedResultId, setSelectedResultId] = useState(null);

  const handleRunStarted = (sessionId) => {
    setActiveSessionId(sessionId);
    setCurrentTab('progress');
  };

  const handleSelectResult = (resultId) => {
    setSelectedResultId(resultId);
    setCurrentTab('bug-detail');
  };

  const handleRegressionStarted = (sessionId) => {
    setActiveSessionId(sessionId);
    setCurrentTab('progress');
  };

  return (
    <div>
      <Dashboard
        currentTab={currentTab}
        onSelectTab={(tab) => setCurrentTab(tab)}
        activeSessionId={activeSessionId}
      />

      <main className="container">
        {currentTab === 'new' && (
          <NewRun onRunStarted={handleRunStarted} />
        )}

        {currentTab === 'progress' && (
          <RunProgress
            sessionId={activeSessionId}
            onViewResults={() => setCurrentTab('results')}
          />
        )}

        {currentTab === 'results' && (
          <Results
            sessionId={activeSessionId}
            onSelectResult={handleSelectResult}
            onRegressionStarted={handleRegressionStarted}
          />
        )}

        {currentTab === 'bug-detail' && (
          <BugDetail
            resultId={selectedResultId}
            onBack={() => setCurrentTab('results')}
          />
        )}

        {currentTab === 'regression' && (
          <Regression
            onRegressionStarted={handleRegressionStarted}
          />
        )}
      </main>
    </div>
  );
}

/**
 * TopBar - Top navigation bar with home link and model status.
 * 
 * Purpose: Display navigation header with home button, current page path, and model status indicator.
 * Shows loading spinner when model status is loading.
 * 
 * Used by: AppLayout
 */
import React from 'react';

interface TopBarProps {
  modelStatus: 'loading' | 'ready' | 'error';
  onHomeClick: () => void;
  headerPath: string;
}

export function TopBar({ modelStatus, onHomeClick, headerPath }: TopBarProps) {
  const statusConfig = {
    loading: { label: 'Loading', className: 'status-badge loading' },
    ready: { label: '✅ Ready', className: 'status-badge ready' },
    error: { label: '❌ Failed', className: 'status-badge error' },
  };

  const status = statusConfig[modelStatus];

  return (
    <div className="topbar">
      <div className="topbar-left">
        <button onClick={onHomeClick} className="text-accent hover:text-gold font-semibold text-sm">
          🏠 Home
        </button>
        {headerPath && (
          <span className="text-text-dim text-xs" style={{ marginLeft: '8px' }}>
            {headerPath}
          </span>
        )}
      </div>
      <div className="topbar-right">
        <span className={status.className}>
          {modelStatus === 'loading' && <span className="spinner-sm" style={{ marginRight: '4px' }} />}
          {status.label}
        </span>
      </div>
    </div>
  );
}
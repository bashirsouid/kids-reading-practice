/**
 * ReviewPage - Step 6: Final review with export options.
 * 
 * Purpose: Display final comic panels with export options (PNG).
 * Provides navigation back to previous step for edits.
 * 
 * Route: /review
 */
import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { PanelGrid } from '../components/panel/PanelGrid';
import { Button } from '../components/ui/Button';

export function ReviewPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'review' });
  }, []);

  const handleExportPNG = () => {
    if (state.jobId) {
      window.open(`/api/export/${state.jobId}`, '_blank');
    }
  };



  const handleBack = () => {
    navigate(projectPath('panelImages'));
  };

  return (
    <div className="main-layout">
      <div className="form-section">
        <div className="text-xs text-text-dim mb-3">Step 6: Complete!</div>
        <h2 className="text-xl text-gold mb-4">🎉 Your Comic Is Ready</h2>

        <div className="mb-4">
          <div className="text-sm font-semibold text-text-dim mb-2">Art Style Used</div>
          <div className="bg-surface2 p-3 rounded-lg">
            <span className="text-gold font-semibold">{state.story?.art_style || 'Modern Pixar 3D animation style'}</span>
            <p className="text-text-dim text-xs mt-1">To change art style, go back to Step 3: Style & Reference</p>
          </div>
        </div>

        <div className="flex gap-3 mb-4">
          <Button variant="primary" onClick={handleExportPNG}>
            Export PNG
          </Button>
        </div>

        <Button variant="secondary" onClick={handleBack} className="w-full">
          ← Back
        </Button>
      </div>

      <div>
        <div className="zoom-controls">
          <Button variant="secondary" size="sm">−</Button>
          <span className="zoom-display">100%</span>
          <Button variant="secondary" size="sm">+</Button>
        </div>
        {state.story?.panels && <PanelGrid panels={state.story.panels} jobId={state.jobId} />}
      </div>
    </div>
  );
}

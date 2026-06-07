/**
 * ReviewPage - Step 6: Final review with export options.
 *
 * Purpose: Display final comic panels with export options (PNG).
 * Provides navigation back to previous step for edits.
 * Supports per-panel regeneration progress display.
 *
 * Route: /review
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { PanelGrid } from '../components/panel/PanelGrid';
import { Button } from '../components/ui/Button';
import { ImageLightbox } from '../components/ui/ImageLightbox';
import { getJobStatus, getPanelImageUrl } from '../services/api';

export function ReviewPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [panelCacheKeys, setPanelCacheKeys] = useState<Record<number, number>>({});

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'review' });
  }, []);

  useEffect(() => {
    if (!state.jobId) return;
    let cancelled = false;

    const refreshStatus = async () => {
      try {
        const status = await getJobStatus(state.jobId!);
        if (cancelled || !status.story) return;
        dispatch({
          type: 'SET_STORY',
          payload: {
            ...(state.story || {}),
            ...status.story,
          },
        });
        if (status.story.panels) {
          setPanelCacheKeys(prev => {
            const next = { ...prev };
            for (const panel of status.story!.panels || []) {
              if (panel.has_image) next[panel.index || 0] = Date.now();
            }
            return next;
          });
        }
      } catch {
      }
    };

    refreshStatus();
    const interval = window.setInterval(refreshStatus, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [state.jobId, dispatch]);

  const handleExportPNG = () => {
    if (state.jobId) {
      window.open(`/api/export/${state.jobId}`, '_blank');
    }
  };

  const handlePanelClick = (index: number) => {
    const panels = state.story?.panels || [];
    const panel = panels[index];
    if (panel?.has_image && state.jobId) {
      const cacheKey = panelCacheKeys[index];
      setLightboxUrl(getPanelImageUrl(state.jobId, index) + (cacheKey ? `?t=${cacheKey}` : ''));
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
        {state.story?.panels && (
          <PanelGrid
            panels={state.story.panels}
            jobId={state.jobId}
            columns={2}
            panelCacheKeys={panelCacheKeys}
            showImageStatus={false}
            onPanelClick={handlePanelClick}
          />
        )}
      </div>
      {lightboxUrl && (
        <ImageLightbox src={lightboxUrl} onClose={() => setLightboxUrl(null)} />
      )}
    </div>
  );
}

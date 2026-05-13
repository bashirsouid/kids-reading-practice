/**
 * PanelBreakdownPage - Step 4: Generate and edit the 6 panel descriptions.
 * 
 * Purpose: Generate 6 panel descriptions with image_prompt and caption fields.
 * Users can edit character names, scene descriptions, and captions for each panel.
 * Proceeding advances job to "panels" stage.
 * 
 * Note: Panels are now generated automatically after synopsis confirmation in step 2.
 * This page allows editing/revising the panel content before image generation.
 * 
 * Route: /panelBreakdown
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { generatePanelBreakdown, proceedToNextStage, updatePanels } from '../services/api';
import { WizardNav } from '../components/ui/WizardNav';
import { Button } from '../components/ui/Button';
import { ErrorMessage } from '../components/ui/ErrorMessage';

export function PanelBreakdownPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [panels, setPanels] = useState(state.story?.panels || []);
  const [error, setError] = useState<string | null>(null);

  // Sync panels from wizard state when story updates
  useEffect(() => {
    if (state.story?.panels && state.story.panels.length > 0) {
      setPanels(state.story.panels);
    }
  }, [state.story]);

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'panelBreakdown' });
  }, []);

  const handleRegenerate = async () => {
    if (!state.jobId) return;
    setError(null);
    try {
      const result = await generatePanelBreakdown(state.jobId);
      setPanels(result.breakdown || []);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to regenerate panel breakdown';
      setError(errorMessage);
    }
  };

  const handlePanelUpdate = (idx: number, field: string, value: string) => {
    const newPanels = [...panels];
    newPanels[idx] = { ...newPanels[idx], [field]: value };
    setPanels(newPanels);
  };

  const handleNext = async () => {
    if (!state.jobId) return;
    
    // Save panel edits to the backend before proceeding
    try {
      const panelsToUpdate = panels.map((p, idx) => ({
        index: idx,
        caption: p.caption,
        image_prompt: p.image_prompt,
        characters: p.characters,
        is_placeholder: p.is_placeholder,
      }));
      await updatePanels(state.jobId, panelsToUpdate);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save panel edits';
      setError(errorMessage);
      return;
    }
    
    // Proceed to panel image generation
    await proceedToNextStage(state.jobId);
    navigate('/panelImages');
  };

  const handleBack = () => {
    navigate('/styleReference');
  };

  return (
    <div className="main-layout">
      <div className="form-section">
        <div className="text-xs text-text-dim mb-3">Step 4: Panel Breakdown</div>
        <h2 className="text-xl text-gold mb-4">📋 Panel Breakdown</h2>

        {error && (
          <ErrorMessage message={error} onDismiss={() => setError(null)} />
        )}

        {panels.length === 0 && (
          <div className="mb-4">
            <p className="text-text-dim text-sm mb-3">
              No panels found. Click below to generate panel breakdown.
            </p>
            <Button
              variant="primary"
              className="w-full mb-3"
              onClick={handleRegenerate}
            >
              📋 Generate Panel Breakdown
            </Button>
          </div>
        )}

        <div className="space-y-3">
          {panels.map((panel, idx) => {
            const isPlaceholder = panel.is_placeholder || 
              (panel.caption && panel.caption.startsWith('[Placeholder'));
            return (
              <div key={idx} className={`card mb-3 ${isPlaceholder ? 'border-dashed border-accent' : ''}`}>
                <div className="font-semibold text-gold mb-2">
                  # {idx + 1} Panel {isPlaceholder && <span className="text-accent text-xs">(PLACEHOLDER - Needs Text)</span>}
                </div>
                <div className="input-area mb-2">
                  <label className="text-xs">Characters</label>
                  <input
                    type="text"
                    value={panel.characters || ''}
                    onChange={(e) => handlePanelUpdate(idx, 'characters', e.target.value)}
                    placeholder="Character names..."
                    className="text-sm"
                  />
                </div>
                <div className="input-area mb-2">
                  <label className="text-xs">Scene Description</label>
                  <textarea
                    rows={2}
                    value={panel.image_prompt || ''}
                    onChange={(e) => handlePanelUpdate(idx, 'image_prompt', e.target.value)}
                    placeholder="Describe the scene..."
                    className="text-sm"
                  />
                </div>
                <div className="input-area">
                  <label className="text-xs">Caption</label>
                  <textarea
                    rows={1}
                    value={panel.caption || ''}
                    onChange={(e) => handlePanelUpdate(idx, 'caption', e.target.value)}
                    placeholder="Panel caption..."
                    className="text-sm"
                  />
                </div>
              </div>
            );
          })}
        </div>

        <WizardNav
          onBack={handleBack}
          onNext={handleNext}
          nextLabel="Next: Generate Images →"
        />
      </div>

      <div>
        <div className="zoom-controls">
          <Button variant="secondary" size="sm">−</Button>
          <span className="zoom-display">100%</span>
          <Button variant="secondary" size="sm">+</Button>
        </div>
        {/* Preview grid */}
      </div>
    </div>
  );
}
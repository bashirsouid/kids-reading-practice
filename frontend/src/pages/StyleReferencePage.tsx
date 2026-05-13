/**
 * StyleReferencePage - Step 3: Select art style and generate master reference image.
 * 
 * Purpose: Allow users to select art style and manage character descriptions.
 * Generates master reference image for character consistency across panels.
 * Proceeding advances job to the panel breakdown step.
 * 
 * Route: /styleReference
 * 
 * Note: Reference generation is explicit; Next is enabled after the reference exists.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { proceedToNextStage, generateMasterReference, updateArtStyle } from '../services/api';
import { WizardNav } from '../components/ui/WizardNav';
import { ArtStyleSelector } from '../components/style/ArtStyleSelector';
import { CharacterList } from '../components/character/CharacterList';
import { Button } from '../components/ui/Button';
import { Spinner } from '../components/ui/Spinner';
import { useWebSocket } from '../hooks/useWebSocket';

export function StyleReferencePage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [artStyle, setArtStyle] = useState(state.story?.art_style || 'Modern Pixar 3D animation style');
  const [characters, setCharacters] = useState(
    state.story?.characters || []
  );
  const [isGeneratingRef, setIsGeneratingRef] = useState(false);
  // Initialize based on whether the story already has a reference image
  const [hasReference, setHasReference] = useState(
    !!state.story?.master_reference
  );
  const [error, setError] = useState<string | null>(null);

  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'styleReference' });
  }, []);

  // Listen for WebSocket updates for this job
  useWebSocket({
    jobId: state.jobId || '',
    onProgress: (progress, total) => {
      // optional: could update UI progress if desired
    },
    onReferenceReady: () => {
      // Master reference is ready - the WebSocket indicates has_reference is true
      // or the stage has moved to panel_breakdown
      setHasReference(true);
      setIsGeneratingRef(false);
    },
    onError: (msg) => {
      setError(msg);
      setIsGeneratingRef(false);
    },
  });

  const handleStyleSelect = async (style: string) => {
    setArtStyle(style);
    if (state.jobId && state.story) {
      dispatch({
        type: 'UPDATE_STORY_FIELD',
        payload: { field: 'art_style', value: style }
      });
      try {
        await updateArtStyle(state.jobId, style);
      } catch (err) {
        console.error('Failed to update art style', err);
      }
    }
  };

  const handleGenerateReference = async () => {
    if (!state.jobId) return;
    setIsGeneratingRef(true);
    setError(null);
    try {
      await updateArtStyle(state.jobId, artStyle);
      await generateMasterReference(state.jobId);
      // WebSocket onReferenceReady will update state
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to generate reference';
      setError(errorMessage);
      setIsGeneratingRef(false);
    }
  };

  const handleNext = async () => {
    if (!state.jobId || !hasReference) return;
    
    try {
      await proceedToNextStage(state.jobId);
      navigate(projectPath('panelBreakdown'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to proceed');
    }
  };

  const handleCharacterUpdate = (idx: number, field: 'name' | 'description', value: string) => {
    const newChars = [...characters];
    newChars[idx] = { ...newChars[idx], [field]: value };
    setCharacters(newChars);
  };

  const handleAddCharacter = () => {
    setCharacters([...characters, { name: `Character ${characters.length + 1}`, description: '' }]);
  };

  const handleRemoveCharacter = (idx: number) => {
    setCharacters(characters.filter((_, i) => i !== idx));
  };

  const handleBack = () => {
    navigate(projectPath('storyContent'));
  };

  return (
    <div className="main-layout">
      <div className="form-section">
        <div className="text-xs text-text-dim mb-3">Step 3: Style & Reference</div>
        <h2 className="text-xl text-gold mb-4">🎨 Style & Character Reference</h2>

        <div className="mb-4">
          <label className="text-sm font-semibold text-text-dim mb-2 block">Art Style</label>
          <ArtStyleSelector selectedStyle={artStyle} onSelect={handleStyleSelect} />
        </div>

        <div className="mb-4">
          <div className="text-sm font-semibold text-text-dim mb-2">Character Descriptions</div>
          <CharacterList
            characters={characters}
            onUpdate={handleCharacterUpdate}
            onAdd={handleAddCharacter}
            onRemove={handleRemoveCharacter}
          />
        </div>

        <div className="mb-4">
          <div className="bg-bg p-4 rounded-lg text-center mb-4">
            {error && (
              <div className="bg-red-900/50 border border-red-500 text-red-200 p-3 rounded-md mb-3 text-sm">
                <strong>Error:</strong> {error}
                <button 
                  onClick={() => setError(null)}
                  className="ml-2 text-red-400 hover:text-red-200"
                >
                  ×
                </button>
              </div>
            )}
            {hasReference ? (
              <div className="flex flex-col items-center">
                <img
                  src={`/api/master-reference/${state.slug}?t=${Date.now()}`}
                  alt="Reference"
                  className="max-w-full rounded-lg cursor-pointer mx-auto mb-3"
                  onError={(e) => {
                    // If image fails to load, indicate that
                    setHasReference(false);
                    setError('Reference image failed to load. Please regenerate.');
                  }}
                />
                <Button 
                  variant="secondary" 
                  size="sm" 
                  onClick={handleGenerateReference} 
                  disabled={isGeneratingRef}
                >
                  {isGeneratingRef ? 'Regenerating...' : '🔄 Regenerate Reference'}
                </Button>
              </div>
            ) : (
              <div>
                {isGeneratingRef && <Spinner className="mx-auto mb-3" />}
                <p className="text-text-dim text-sm mb-3">
                  {isGeneratingRef
                    ? 'Generating reference image... This may take a minute.'
                    : 'Click to generate the master reference image'
                  }
                </p>
                {!isGeneratingRef && (
                  <>
                    <Button variant="primary" onClick={handleGenerateReference}>🖼️ Generate Reference Image</Button>
                    <p className="text-text-dim text-xs mt-3">
                      The reference image ensures character consistency across all panels
                    </p>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        <WizardNav
          onBack={handleBack}
          onNext={handleNext}
          nextLabel="Next: Panel Breakdown →"
          nextDisabled={!hasReference || isGeneratingRef}
        />
      </div>

      <div />
    </div>
  );
}

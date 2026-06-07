/**
 * ComicInfoPage - Step 1: Select story mode and generate initial story.
 * 
 * Purpose: Allow users to choose story generation mode (random/themed/custom/fullstory)
 * and provide input text when required. Generates story and navigates to Step 2.
 * 
 * Route: /comicInfo
 * 
 * Note: Only generates story. Does NOT generate reference or panels.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { generateStory } from '../services/api';
import { Button } from '../components/ui/Button';
import { ModeSelector } from '../components/mode/ModeSelector';
import { ErrorMessage } from '../components/ui/ErrorMessage';

// Quick theme categories for easy selection
const THEME_CATEGORIES = [
  { label: '🦄 Unicorns', value: 'unicorns' },
  { label: '🏴 Pirates', value: 'pirates' },
  { label: '🌊 Ocean Life', value: 'ocean life' },
  { label: '🦖 Dinosaurs', value: 'dinosaurs' },
  { label: '🚀 Space', value: 'space adventure' },
  { label: '🐾 Animals', value: 'forest animals' },
  { label: '🧙 Magic', value: 'magic fantasy' },
  { label: '🤖 Robots', value: 'friendly robots' },
];

export function ComicInfoPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [theme, setTheme] = useState('');
  const [storyInput, setStoryInput] = useState('');
  const [fullStoryInput, setFullStoryInput] = useState('');
  const [randomnessLevel, setRandomnessLevel] = useState(5); // Default to balanced (5)
  const [isGenerating, setIsGenerating] = useState(false);
  const [storyGenerated, setStoryGenerated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const projectPath = (page: string, slug = state.slug) => slug ? `/${slug}/${page}` : `/${page}`;

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'comicInfo' });
  }, []);

  // Connect to WebSocket to receive story data when generated
  useEffect(() => {
    if (!state.jobId || storyGenerated) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${state.jobId}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.error) {
          setError(data.error);
          setIsGenerating(false);
          return;
        }
        if (data.story) {
          // Store the generated story in wizard state
          dispatch({ type: 'SET_STORY', payload: {
            title: data.story.title,
            synopsis: data.story.synopsis,
            art_style: data.story.art_style,
            character_bible: data.story.character_bible,
            characters: data.story.characters,
            panels: data.story.panels,
            master_reference: data.story.master_reference,
          }});
          if (data.slug) {
            dispatch({ type: 'SET_SLUG', payload: data.slug });
          }
          setStoryGenerated(true);
          navigate(projectPath('storyContent', data.slug || state.slug));
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    return () => ws.close();
  }, [state.jobId, storyGenerated, dispatch, navigate]);

  const handleModeSelect = (mode: string) => {
    dispatch({ type: 'SET_MODE', payload: mode as any });
  };

  const handleThemeCategorySelect = (themeValue: string) => {
    setTheme(themeValue);
    dispatch({ type: 'SET_MODE', payload: 'themed' });
  };

  const handleRandomnessChange = (value: number) => {
    setRandomnessLevel(value);
    dispatch({ type: 'SET_RANDOMNESS_LEVEL', payload: value });
  };

  const handleGenerate = async () => {
    let text = '';
    if (state.mode === 'themed') text = theme.trim();
    else if (state.mode === 'custom') text = storyInput.trim();
    else if (state.mode === 'fullstory') text = fullStoryInput.trim();

    if (state.mode === 'themed' && !text) {
      setError('Please enter a theme');
      return;
    }
    if (state.mode === 'custom' && !text) {
      setError('Please describe your story');
      return;
    }
    if (state.mode === 'fullstory' && !text) {
      setError('Please provide your full story text');
      return;
    }

    setIsGenerating(true);
    setError(null);
    try {
      const result = await generateStory({ 
        mode: state.mode, 
        text,
        randomness_level: randomnessLevel 
      });
      if (result.job_id) {
        dispatch({ type: 'SET_JOB_ID', payload: result.job_id });
        if (result.slug) {
          dispatch({ type: 'SET_SLUG', payload: result.slug });
          window.history.replaceState(null, '', projectPath('comicInfo', result.slug));
        }
        // Wait for story data via WebSocket before navigating
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to generate story';
      setError(errorMessage);
      setIsGenerating(false);
    }
  };

  // Get randomness label based on level
  const getRandomnessLabel = () => {
    if (randomnessLevel <= 2) return 'Focused & Predictable';
    if (randomnessLevel <= 4) return 'Slightly Varied';
    if (randomnessLevel <= 6) return 'Balanced';
    if (randomnessLevel <= 8) return 'Very Creative';
    return 'Wild & Unexpected';
  };

  return (
    <div className="max-w-5xl mx-auto">
      <div className="form-section">
        <div className="text-xs text-text-dim mb-3">Step 1: Comic Information</div>
        <h2 className="text-xl text-gold mb-3">📝 Create Your Comic</h2>

        {error && (
          <ErrorMessage message={error} onDismiss={() => setError(null)} />
        )}

        <div className="mb-4">
          <label className="text-xs font-semibold text-text-dim mb-2 block">Story Mode</label>
          <ModeSelector selectedMode={state.mode} onSelect={handleModeSelect} />
        </div>

        {state.mode === 'themed' && (
          <>
            <div className="input-area mb-4">
              <label>Theme</label>
              <input
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                placeholder="e.g. dinosaurs, space pirates..."
              />
            </div>
            <div className="mb-4">
              <label className="text-xs font-semibold text-text-dim mb-2 block">Quick Theme Categories</label>
              <div className="flex flex-wrap gap-2">
                {THEME_CATEGORIES.map((cat) => (
                  <button
                    key={cat.value}
                    type="button"
                    onClick={() => handleThemeCategorySelect(cat.value)}
                    className="px-3 py-1 text-xs rounded-full transition-all duration-200"
                    style={{
                      backgroundColor: theme === cat.value ? 'var(--color-gold)' : 'var(--color-surface-light)',
                      color: theme === cat.value ? 'var(--color-bg-primary)' : 'var(--color-text-dim)',
                      border: theme === cat.value ? '2px solid var(--color-gold)' : '1px solid var(--color-border)',
                    }}
                  >
                    {cat.label}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {state.mode === 'custom' && (
          <div className="input-area">
            <label>Story Description</label>
            <textarea
              value={storyInput}
              onChange={(e) => setStoryInput(e.target.value)}
              placeholder="A brave robot discovers..."
            />
          </div>
        )}

        {state.mode === 'fullstory' && (
          <div className="input-area">
            <label>Full Story Text</label>
            <textarea
              value={fullStoryInput}
              onChange={(e) => setFullStoryInput(e.target.value)}
              placeholder="Once upon a time... (provide your complete story here)"
            />
          </div>
        )}

        {/* Randomness Level Slider */}
        <div className="mb-4">
          <div className="flex justify-between items-center mb-2">
            <label className="text-xs font-semibold text-text-dim">Randomness Level</label>
            <span className="text-xs font-medium" style={{ color: 'var(--color-gold)' }}>
              {getRandomnessLabel()}
            </span>
          </div>
          <input
            type="range"
            min="1"
            max="10"
            value={randomnessLevel}
            onChange={(e) => handleRandomnessChange(parseInt(e.target.value))}
            className="w-full h-2 bg-surface-light rounded-full appearance-none cursor-pointer slider"
            style={{
              background: `linear-gradient(to right, var(--color-gold) 0%, var(--color-gold) ${((randomnessLevel - 1) / 9) * 100}%, var(--color-surface-light) ${((randomnessLevel - 1) / 9) * 100}%, var(--color-surface-light) 100%)`,
            }}
          />
          <div className="flex justify-between text-xs text-text-dim mt-1">
            <span>Conservative</span>
            <span>Balanced</span>
            <span>Wild</span>
          </div>
        </div>

        <div className="mt-5">
          <Button
            variant="primary"
            className="w-full"
            onClick={handleGenerate}
            disabled={isGenerating}
          >
            {isGenerating ? '⏳ Generating...' : '🚀 Generate Story'}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * AppLayout - Main application layout with Outlet.
 * 
 * Purpose: Provide consistent page structure with TopBar, content area, and Footer.
 * Displays current page path in header based on wizard state.
 * Polls health endpoint to update model status.
 * 
 * Used by: All pages via router
 */
import React, { useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { useWizard } from '../../context/WizardContext';
import { TopBar } from './TopBar';
import { Footer } from './Footer';
import { checkHealth } from '../../services/api';

export function AppLayout() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();

  const handleHomeClick = () => {
    navigate('/');
  };

  const getHeaderPath = () => {
    const paths: Record<string, string> = {
      home: '',
      comicInfo: 'Step 1 / Comic Info',
      storyContent: 'Step 2 / Story',
      styleReference: 'Step 3 / Style & Reference',
      panelBreakdown: 'Step 4 / Panel Breakdown',
      panelImages: 'Step 5 / Panel Images',
      review: 'Step 6 / Review',
    };
    return paths[state.page] || '';
  };

  // Poll health endpoint to update model status
  useEffect(() => {
    // Use a ref to track if we've detected models are ready
    let modelsReady = false;
    let intervalId: ReturnType<typeof setInterval>;

    const checkModelStatus = async () => {
      // Skip if already detected as ready
      if (modelsReady) return;

      try {
        const health = await checkHealth();
        if (health.models_loaded) {
          modelsReady = true;
          dispatch({ type: 'SET_MODEL_STATUS', payload: 'ready' });
          clearInterval(intervalId);
        } else if (health.models_loading) {
          dispatch({ type: 'SET_MODEL_STATUS', payload: 'loading' });
        } else {
          // Neither loaded nor loading - initial state, still loading
          dispatch({ type: 'SET_MODEL_STATUS', payload: 'loading' });
        }
      } catch (error) {
        console.error('Health check failed:', error);
        dispatch({ type: 'SET_MODEL_STATUS', payload: 'error' });
      }
    };

    // Check immediately on mount, then poll every 2 seconds
    checkModelStatus();
    intervalId = setInterval(checkModelStatus, 2000);

    return () => {
      clearInterval(intervalId);
    };
    // Empty deps array - run once on mount
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar
        modelStatus={state.modelStatus}
        onHomeClick={handleHomeClick}
        headerPath={getHeaderPath()}
      />
      <div className="container flex-1">
        <Outlet />
      </div>
      <Footer />
    </div>
  );
}
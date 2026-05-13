/**
 * HomePage - Landing page with option to create new comic or load recent projects.
 * 
 * Purpose: Entry point of the wizard. Resets state and navigates to Step 1 (ComicInfo).
 * Displays comic title and primary call-to-action button.
 * 
 * Route: /
 */
import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { getRecentProjects } from '../services/api';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';

export function HomePage() {
  const navigate = useNavigate();
  const { dispatch } = useWizard();

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'home' });
    loadProjects();
  }, []);

  const loadProjects = async () => {
    try {
      const projects = await getRecentProjects();
      // Store in local state for display
    } catch (error) {
      console.error('Failed to load projects:', error);
    }
  };

  const handleCreateNew = () => {
    dispatch({ type: 'RESET' });
    navigate('/comicInfo');
  };

  return (
    <div className="flex justify-center">
      <Card className="max-w-lg mt-20 text-center">
        <h1 className="text-3xl mb-2 bg-gradient-to-r from-gold to-accent bg-clip-text text-transparent">
          🎨 Comic Generator
        </h1>
        <p className="text-text-dim mb-8">AI-powered comic book creation</p>
        <Button variant="primary" size="default" onClick={handleCreateNew}>
          ✨ Create New Comic
        </Button>
      </Card>
    </div>
  );
}
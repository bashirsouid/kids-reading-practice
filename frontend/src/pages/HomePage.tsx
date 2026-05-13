/**
 * HomePage - Landing page with option to create new comic or load recent projects.
 * 
 * Purpose: Entry point of the wizard. Resets state and navigates to Step 1 (ComicInfo).
 * Displays comic title and primary call-to-action button.
 * 
 * Route: /
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { getRecentProjects } from '../services/api';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';

export function HomePage() {
  const navigate = useNavigate();
  const { dispatch } = useWizard();
  const [projects, setProjects] = useState<Array<{ slug: string; title: string; created_at: number; status?: string; stage?: string }>>([]);

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'home' });
    loadProjects();
  }, []);

  const loadProjects = async () => {
    try {
      const recent = await getRecentProjects();
      setProjects(recent);
    } catch (error) {
      console.error('Failed to load projects:', error);
    }
  };

  const handleCreateNew = () => {
    dispatch({ type: 'RESET' });
    navigate('/comicInfo');
  };

  return (
    <div className="flex flex-col items-center px-4">
      <Card className="max-w-lg mt-20 text-center mb-8 w-full">
        <h1 className="text-3xl mb-2 bg-gradient-to-r from-gold to-accent bg-clip-text text-transparent">
          🎨 Comic Generator
        </h1>
        <p className="text-text-dim mb-8">AI-powered comic book creation</p>
        <Button variant="primary" size="default" onClick={handleCreateNew}>
          ✨ Create New Comic
        </Button>
      </Card>

      {projects.length > 0 && (
        <Card className="max-w-3xl w-full">
          <h2 className="text-xl text-gold mb-4 text-center">Recent Projects</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {projects.map(p => (
              <div 
                key={p.slug} 
                className="bg-surface2 p-4 rounded-lg border border-border hover:border-gold cursor-pointer transition-colors"
                onClick={() => navigate(`/${p.slug}`)}
              >
                <div className="font-semibold text-lg truncate text-white" title={p.title}>{p.title}</div>
                <div className="text-xs text-text-dim mt-2">
                  {new Date(p.created_at * 1000).toLocaleString()}
                </div>
                <div className="text-xs text-gold mt-1 capitalize">
                  {(p.stage || p.status || 'saved').replace(/_/g, ' ')}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { loadProject } from '../services/api';
import { Spinner } from '../components/ui/Spinner';

export function ProjectLoader() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { dispatch } = useWizard();
  const [error, setError] = useState<string | null>(null);

  const projectPath = (page: string) => `/${slug!}/${page}`;

  useEffect(() => {
    if (!slug) {
      navigate('/');
      return;
    }

    const fetchProject = async () => {
      try {
        const project = await loadProject(slug);
        
        // Update context with project data
        dispatch({ type: 'SET_JOB_ID', payload: project.job_id });
        dispatch({ type: 'SET_SLUG', payload: slug });
        
        // Ensure story is initialized if we have data
        if (project.story) {
          dispatch({
            type: 'SET_STORY',
            payload: {
              title: project.story.title || '',
              synopsis: project.story.synopsis || '',
              art_style: project.story.art_style || '',
              characters: project.story.characters || [],
              panels: project.story.panels || [],
            }
          });
        }

        if (project.status === 'error' && project.story?.panels?.length) {
          navigate(projectPath(project.has_reference ? 'panelImages' : 'styleReference'));
          return;
        }
        
        // Redirect to appropriate stage based on job.stage
        switch (project.stage) {
          case 'input':
          case 'synopsis':
            navigate(projectPath('comicInfo'));
            break;
          case 'story':
            navigate(projectPath('storyContent'));
            break;
          case 'reference':
            navigate(projectPath('styleReference'));
            break;
          case 'panel_breakdown':
            if (project.has_reference) {
                navigate(projectPath('panelBreakdown'));
            } else {
                navigate(projectPath('styleReference'));
            }
            break;
          case 'panels':
            navigate(projectPath(project.has_reference ? 'panelImages' : 'styleReference'));
            break;
          case 'complete':
            navigate(projectPath('review'));
            break;
          case 'error':
            if (project.story?.panels?.length) {
              navigate(projectPath(project.has_reference ? 'panelImages' : 'styleReference'));
            } else {
              setError(project.error || 'This project is in an error state.');
            }
            break;
          default:
            navigate('/');
        }
      } catch (err) {
        console.error('Failed to load project:', err);
        setError('Project not found or failed to load.');
      }
    };

    fetchProject();
  }, [slug, navigate, dispatch]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh]">
        <div className="bg-red-900/50 border border-red-500 text-red-200 p-4 rounded-md mb-4 max-w-md text-center">
          <h2 className="text-xl font-bold mb-2">Error</h2>
          <p>{error}</p>
        </div>
        <button 
          className="btn btn-primary px-4 py-2 bg-gold hover:bg-gold/80 text-black rounded font-medium"
          onClick={() => navigate('/')}
        >
          Return Home
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[50vh]">
      <Spinner />
      <p className="mt-4 text-text-dim text-lg">Loading project "{slug}"...</p>
    </div>
  );
}

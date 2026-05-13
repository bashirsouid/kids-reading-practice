import React from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider, Navigate } from 'react-router-dom';
import { WizardProvider } from './context/WizardContext';
import { AppLayout } from './components/layout/AppLayout';
import { HomePage } from './pages/HomePage';
import { ComicInfoPage } from './pages/ComicInfoPage';
import { StoryContentPage } from './pages/StoryContentPage';
import { StyleReferencePage } from './pages/StyleReferencePage';
import { PanelBreakdownPage } from './pages/PanelBreakdownPage';
import { PanelImagesPage } from './pages/PanelImagesPage';
import { ReviewPage } from './pages/ReviewPage';
import { ProjectLoader } from './pages/ProjectLoader';
import './index.css';

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'comicInfo', element: <ComicInfoPage /> },
      { path: 'storyContent', element: <StoryContentPage /> },
      { path: 'styleReference', element: <StyleReferencePage /> },
      { path: 'panelBreakdown', element: <PanelBreakdownPage /> },
      { path: 'panelImages', element: <PanelImagesPage /> },
      { path: 'review', element: <ReviewPage /> },
      { path: ':slug', element: <ProjectLoader /> },
      { path: ':slug/comicInfo', element: <ComicInfoPage /> },
      { path: ':slug/storyContent', element: <StoryContentPage /> },
      { path: ':slug/styleReference', element: <StyleReferencePage /> },
      { path: ':slug/panelBreakdown', element: <PanelBreakdownPage /> },
      { path: ':slug/panelImages', element: <PanelImagesPage /> },
      { path: ':slug/review', element: <ReviewPage /> },
    ],
  },
]);

function App() {
  return (
    <WizardProvider>
      <RouterProvider router={router} />
    </WizardProvider>
  );
}

createRoot(document.getElementById('root')!).render(<App />);

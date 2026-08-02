import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ViewModeProvider } from './hooks/useViewMode';
import { ArtifactTimelinePage } from './pages/ArtifactTimelinePage';
import { EpicDetailPage } from './pages/EpicDetailPage';
import { EpicListPage } from './pages/EpicListPage';
import { HomePage } from './pages/HomePage';
import { KnowledgeBasePage } from './pages/KnowledgeBasePage';
import { SearchPage } from './pages/SearchPage';
import { TodosListPage } from './pages/TodosListPage';

/**
 * Root application component with client-side routing.
 *
 * Wraps all pages in the shared Layout shell and defines
 * route paths for the dashboard views.
 */
export function App(): React.JSX.Element {
  return (
    <ViewModeProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/epics" element={<EpicListPage />} />
            <Route path="/epics/:id" element={<EpicDetailPage />} />
            <Route path="/timeline/:epicId" element={<ArtifactTimelinePage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/todos" element={<TodosListPage />} />
            <Route path="/knowledge" element={<KnowledgeBasePage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ViewModeProvider>
  );
}

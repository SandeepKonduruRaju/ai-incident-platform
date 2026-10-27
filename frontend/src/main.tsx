import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
// Self-hosted fonts (no external font requests): Public Sans for the interface, Source Serif 4 for reports.
import '@fontsource/public-sans/400.css';
import '@fontsource/public-sans/600.css';
import '@fontsource/public-sans/700.css';
import '@fontsource/source-serif-4/400.css';
import '@fontsource/source-serif-4/600.css';
import { App } from './App';
import { AuthProvider } from './auth/AuthContext';
import { Router } from './router';
import { applyTheme, readThemePreference } from './theme';
import './styles/tokens.css';
import './index.css';

applyTheme(readThemePreference()); // before the first render, so a pinned theme does not flash

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <Router>
        <App />
      </Router>
    </AuthProvider>
  </StrictMode>,
);

import {createBrowserRouter, Link, useRouteError} from 'react-router';
import {Compass, TriangleAlert} from 'lucide-react';
import {AppShell} from '@/components/layout/AppShell';
import {EmptyState} from '@/components/ui/Feedback';
import {Button, buttonClass} from '@/components/ui/Button';
import {DashboardPage} from '@/pages/DashboardPage';
import {NewAnalysisPage} from '@/pages/NewAnalysisPage';
import {AnalysesPage} from '@/pages/AnalysesPage';
import {AnalysisDetailPage} from '@/pages/AnalysisDetailPage';
import {RulesPage} from '@/pages/RulesPage';
import {RuleAssistantPage} from '@/pages/RuleAssistantPage';
import {SchedulesPage} from '@/pages/SchedulesPage';
import {ScheduleEditPage} from '@/pages/ScheduleEditPage';
import {ScheduleDetailPage} from '@/pages/ScheduleDetailPage';
import {RuleGroupsPage} from '@/pages/RuleGroupsPage';
import {ConnectionsPage} from '@/pages/ConnectionsPage';
import {SettingsPage} from '@/pages/SettingsPage';

function NotFound() {
  return (
    <EmptyState
      icon={<Compass />}
      title="Sayfa bulunamadı"
      description="Aradığınız sayfa taşınmış ya da hiç var olmamış olabilir."
      action={
        <Link to="/" className={buttonClass('primary')}>
          Genel Bakış’a dön
        </Link>
      }
    />
  );
}

function RouteError() {
  const error = useRouteError();
  return (
    <EmptyState
      icon={<TriangleAlert className="text-bad" />}
      title="Beklenmeyen bir hata oluştu"
      description={error instanceof Error ? error.message : 'Sayfa görüntülenirken bir sorun çıktı.'}
      action={<Button onClick={() => window.location.reload()}>Sayfayı yenile</Button>}
    />
  );
}

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      {
        errorElement: <RouteError />,
        children: [
          {index: true, element: <DashboardPage />},
          {path: 'analyses/new', element: <NewAnalysisPage />},
          {path: 'analyses', element: <AnalysesPage />},
          {path: 'analyses/:id', element: <AnalysisDetailPage />},
          {path: 'schedules', element: <SchedulesPage />},
          {path: 'schedules/new', element: <ScheduleEditPage />},
          {path: 'schedules/:id', element: <ScheduleDetailPage />},
          {path: 'schedules/:id/edit', element: <ScheduleEditPage />},
          {path: 'rules', element: <RulesPage />},
          {path: 'rules/assistant', element: <RuleAssistantPage />},
          {path: 'rules/assistant/:id', element: <RuleAssistantPage />},
          {path: 'rule-groups', element: <RuleGroupsPage />},
          {path: 'connections', element: <ConnectionsPage />},
          {path: 'settings', element: <SettingsPage />},
          {path: '*', element: <NotFound />},
        ],
      },
    ],
  },
]);

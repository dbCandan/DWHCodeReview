import {useEffect} from "react";
import {Link} from "react-router";
import {QualityPulse} from "@/components/review/QualityPulse";
import {Badge} from "@/components/ui/Badge";
import {Icon, type IconName} from "@/components/ui/Icon";
import {EmptyState, ErrorState, LoadingState} from "@/components/ui/States";
import {useAuth} from "@/contexts/AuthContext";
import {useIntl} from "@/contexts/IntlContext";
import {useResource} from "@/hooks/useResource";
import {roleLabel} from "@/lib/access";
import {config} from "@/lib/config";
import {describeError} from "@/lib/errorMessages";
import {formatDateTime, formatNumber} from "@/lib/format";
import {RUN_STATUS} from "@/lib/reviewResults";
import {ReviewService} from "@/services/reviews";

interface Action {
  to: string;
  icon: IconName;
  title: string;
  text: string;
}

const START: Action[] = [
  {to: "/inceleme", icon: "database", title: "Nesne incelemesi", text: "SQL Server nesnelerini seçin, kurallarla inceleyin."},
  {to: "/sql-inceleme", icon: "code", title: "SQL betiği incelemesi", text: "Metni yapıştırın, satır referanslı bulgular alın."},
  {to: "/zamanlanmis-incelemeler", icon: "clock", title: "Zamanlanmış incelemeler", text: "Düzenli çalışsın, özeti e-postayla gelsin."},
];

/**
 * The signed-in start page: a short welcome, the three ways to start a review, the user's latest
 * reviews and the quality pulse.
 */
export default function HomePage() {
  const {user, access} = useAuth();
  const {t} = useIntl();
  useEffect(() => {
    document.title = config.productName;
  }, []);

  return (
    <div className="page home">
      <section className="home-welcome" aria-labelledby="home-title">
        <div className="stack-tight">
          <h1 id="home-title">{config.productName}</h1>
          <p className="home-lead">SQL kodunuzu yayımlanmış kurallarla, kurum içi LLM ile inceleyin; bulguları satır satır görün.</p>
        </div>
        <div className="home-welcome-side">
          <Badge tone="primary">{user?.is_super_admin ? t("home.overview.superAdmin") : roleLabel(user?.role)}</Badge>
          <span className="subtle">
            <kbd>Ctrl</kbd> + <kbd>K</kbd> ile her yere hızlı geçin
          </span>
        </div>
      </section>

      {access.review && (
        <>
          <nav className="start-grid" aria-label="İncelemeye başla">
            {START.map((action) => (
              <Link key={action.to} to={action.to} className="start-card">
                <span className="start-icon">
                  <Icon name={action.icon} />
                </span>
                <span className="stack-tight grow">
                  <strong>{action.title}</strong>
                  <span className="action-text">{action.text}</span>
                </span>
                <Icon name="arrowRight" className="start-arrow" />
              </Link>
            ))}
          </nav>
          <div className="home-grid">
            <RecentReviews />
            <QualityPulse />
          </div>
        </>
      )}
    </div>
  );
}

/** The user's five latest reviews; each opens in the history. */
function RecentReviews() {
  const runs = useResource("home:recent-runs", (signal) => ReviewService.runs("mine", 1, 5, signal));
  return (
    <section className="card" aria-labelledby="home-recent">
      <div className="card-header">
        <h2 id="home-recent">Son incelemeleriniz</h2>
        <Link to="/gecmis">Tümünü gör</Link>
      </div>
      <div className="card-body">
        {runs.status === "error" && <ErrorState message={describeError(runs.error)} onRetry={runs.reload} />}
        {runs.data === undefined && runs.status !== "error" && <LoadingState label="İncelemeler yükleniyor…" />}
        {runs.data && runs.data.items.length === 0 && (
          <EmptyState title="Henüz inceleme yok" icon="sparkles">
            Yukarıdan bir inceleme başlatın; sonuçlar burada görünür.
          </EmptyState>
        )}
        {runs.data && runs.data.items.length > 0 && (
          <ul className="list recent-list">
            {runs.data.items.map((run) => (
              <li key={run.id}>
                <Link to={`/gecmis?run=${encodeURIComponent(run.id)}`} className="recent-row">
                  <span className="stat-icon">
                    <Icon name={run.kind === "script" ? "code" : run.kind === "scheduled" ? "clock" : "database"} />
                  </span>
                  <span className="grow stack-tight">
                    <strong className="truncate">{run.title}</strong>
                    <span className="subtle truncate">{formatDateTime(run.started_at)}</span>
                  </span>
                  <span className="recent-meta">
                    <Badge tone={RUN_STATUS[run.status].tone}>{RUN_STATUS[run.status].label}</Badge>
                    <span className="subtle tabular">{formatNumber(run.finding_count)} bulgu</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

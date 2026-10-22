// Route is intentionally pre-registered for generated routes.
import { Route } from "react-router";
// PermissionRoute is intentionally pre-registered for generated protected routes.
import { PermissionRoute } from "@/components/auth/PermissionRoute";
import { RoleRoute } from "@/components/auth/RoleRoute";
import { MovedTo } from "@/components/layout/MovedTo";
import {
  AdminPage,
  ObjectReviewPage,
  PublishedRulesPage,
  ScheduledReviewsPage,
  ScriptReviewPage,
  ReviewHistoryPage,
} from "@/generated/lazyPages";
// kt-scaffold:imports

void Route;
void PermissionRoute;

/**
 * sql-review and application-foundation pages; the backend authorizes every request. Each way to
 * review, the history and the rule library is its own page in the side menu; the super admin's
 * screens live under /yonetim. Earlier addresses send their visitors on.
 */
export const GeneratedRoutes = (
  <>
    {/* kt-scaffold:routes */}
    <Route path="/inceleme" element={<RoleRoute require="review"><ObjectReviewPage /></RoleRoute>} />
    <Route path="/sql-inceleme" element={<RoleRoute require="review"><ScriptReviewPage /></RoleRoute>} />
    <Route path="/zamanlanmis-incelemeler" element={<RoleRoute require="review"><ScheduledReviewsPage /></RoleRoute>} />
    <Route path="/gecmis" element={<RoleRoute require="review"><ReviewHistoryPage /></RoleRoute>} />
    <Route path="/yayimlanmis-kurallar" element={<RoleRoute require="review"><PublishedRulesPage /></RoleRoute>} />
    <Route path="/yonetim" element={<AdminPage />} />
    <Route path="/yonetim/:section" element={<AdminPage />} />
    <Route path="/kural-onerilerim" element={<MovedTo to="/yayimlanmis-kurallar" />} />
    <Route path="/kural-onaylari" element={<MovedTo to="/yonetim" />} />
    <Route path="/kurallar" element={<MovedTo to="/yonetim/kurallar" />} />
    <Route path="/ayarlar/sql" element={<MovedTo to="/yonetim/sql" />} />
    <Route path="/ayarlar/llm" element={<MovedTo to="/yonetim/llm" />} />
    <Route path="/llm-cagrilari" element={<MovedTo to="/yonetim/llm-cagrilari" />} />
    <Route path="/ayarlar/zamanlama" element={<MovedTo to="/yonetim/zamanlama" />} />
    <Route path="/kullanicilar" element={<MovedTo to="/yonetim/kullanicilar" />} />
  </>
);

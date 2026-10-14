// Route is intentionally pre-registered for generated routes.
import { Route } from "react-router";
// PermissionRoute is intentionally pre-registered for generated protected routes.
import { PermissionRoute } from "@/components/auth/PermissionRoute";
import { RoleRoute } from "@/components/auth/RoleRoute";
import {
  LlmCallsPage,
  LlmConnectionPage,
  ObjectReviewPage,
  PublishedRulesPage,
  ReviewHistoryPage,
  RuleApprovalsPage,
  RuleProposalsPage,
  RulesPage,
  ScheduledReviewSettingsPage,
  ScheduledReviewsPage,
  ScriptReviewPage,
  SqlConnectionPage,
  UserAdministrationPage,
} from "@/generated/lazyPages";
// kt-scaffold:imports

void Route;
void PermissionRoute;

/** sql-review and application-foundation pages; the backend authorizes every request. */
export const GeneratedRoutes = (
  <>
    {/* kt-scaffold:routes */}
    <Route path="/inceleme" element={<RoleRoute require="review"><ObjectReviewPage /></RoleRoute>} />
    <Route path="/sql-inceleme" element={<RoleRoute require="review"><ScriptReviewPage /></RoleRoute>} />
    <Route path="/gecmis" element={<RoleRoute require="review"><ReviewHistoryPage /></RoleRoute>} />
    <Route
      path="/zamanlanmis-incelemeler"
      element={<RoleRoute require="review"><ScheduledReviewsPage /></RoleRoute>}
    />
    <Route
      path="/yayimlanmis-kurallar"
      element={<RoleRoute require="review"><PublishedRulesPage /></RoleRoute>}
    />
    <Route path="/kurallar" element={<RoleRoute require="manageRules"><RulesPage /></RoleRoute>} />
    <Route
      path="/kural-onerilerim"
      element={<RoleRoute require="review"><RuleProposalsPage /></RoleRoute>}
    />
    <Route
      path="/kural-onaylari"
      element={<RoleRoute require="administerUsers"><RuleApprovalsPage /></RoleRoute>}
    />
    <Route path="/ayarlar/sql" element={<RoleRoute require="manageRules"><SqlConnectionPage /></RoleRoute>} />
    <Route path="/ayarlar/llm" element={<RoleRoute require="manageRules"><LlmConnectionPage /></RoleRoute>} />
    <Route path="/llm-cagrilari" element={<RoleRoute require="manageRules"><LlmCallsPage /></RoleRoute>} />
    <Route
      path="/ayarlar/zamanlama"
      element={<RoleRoute require="administerUsers"><ScheduledReviewSettingsPage /></RoleRoute>}
    />
    <Route
      path="/kullanicilar"
      element={<RoleRoute require="administerUsers"><UserAdministrationPage /></RoleRoute>}
    />
  </>
);

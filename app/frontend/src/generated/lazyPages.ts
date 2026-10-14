import { lazy } from "react";

/** Route pages load on first visit. */
export const ObjectReviewPage = lazy(() => import("@/pages/ObjectReviewPage"));
export const ScriptReviewPage = lazy(() => import("@/pages/ScriptReviewPage"));
export const ReviewHistoryPage = lazy(() => import("@/pages/ReviewHistoryPage"));
export const ScheduledReviewsPage = lazy(() => import("@/pages/ScheduledReviewsPage"));
export const ScheduledReviewSettingsPage = lazy(() => import("@/pages/ScheduledReviewSettingsPage"));
export const PublishedRulesPage = lazy(() => import("@/pages/PublishedRulesPage"));
export const RulesPage = lazy(() => import("@/pages/RulesPage"));
export const RuleProposalsPage = lazy(() => import("@/pages/RuleProposalsPage"));
export const RuleApprovalsPage = lazy(() => import("@/pages/RuleApprovalsPage"));
export const SqlConnectionPage = lazy(() => import("@/pages/SqlConnectionPage"));
export const LlmConnectionPage = lazy(() => import("@/pages/LlmConnectionPage"));
export const LlmCallsPage = lazy(() => import("@/pages/LlmCallsPage"));
export const UserAdministrationPage = lazy(() => import("@/pages/UserAdministrationPage"));


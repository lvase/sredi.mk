import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { PublicLayout } from "../layouts/PublicLayout";
import { StaffLayout } from "../layouts/StaffLayout";
import { HomePage } from "../pages/HomePage";
import { MunicipalityPage } from "../pages/MunicipalityPage";
import { ReportPage } from "../pages/ReportPage";
import { TrackPage } from "../pages/TrackPage";
import { LegalPage } from "../pages/LegalPage";
import { LoginPage } from "../pages/LoginPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { LoadingState } from "../components/LoadingState";

const StatisticsPage = lazy(() => import("../pages/StatisticsPage").then((module) => ({ default: module.StatisticsPage })));
const StaffDashboardPage = lazy(() => import("../pages/staff/StaffDashboardPage").then((module) => ({ default: module.StaffDashboardPage })));
const StaffIssueDetailPage = lazy(() => import("../pages/staff/StaffIssueDetailPage").then((module) => ({ default: module.StaffIssueDetailPage })));
const StaffUserCreatePage = lazy(() => import("../pages/staff/StaffUserCreatePage").then((module) => ({ default: module.StaffUserCreatePage })));
const SecurityPage = lazy(() => import("../pages/staff/SecurityPage").then((module) => ({ default: module.SecurityPage })));

export function App() {
  return (
    <Suspense fallback={<LoadingState />}><Routes>
      <Route element={<PublicLayout />}>
        <Route index element={<HomePage />} />
        <Route path="privatnost" element={<LegalPage kind="privacy" />} />
        <Route path="uslovi" element={<LegalPage kind="terms" />} />
        <Route path="login" element={<LoginPage />} />
        <Route path=":municipalitySlug" element={<MunicipalityPage />} />
        <Route path=":municipalitySlug/prijavi" element={<ReportPage />} />
        <Route path=":municipalitySlug/statistika" element={<StatisticsPage />} />
        <Route path=":municipalitySlug/sledi" element={<TrackPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      <Route path="staff" element={<StaffLayout />}>
        <Route index element={<StaffDashboardPage />} />
        <Route path="issues/:issueId" element={<StaffIssueDetailPage />} />
        <Route path="users/new" element={<StaffUserCreatePage />} />
        <Route path="security" element={<SecurityPage />} />
      </Route>
    </Routes></Suspense>
  );
}

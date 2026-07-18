import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "@/layouts/AppShell";
import { AboutPage } from "@/pages/AboutPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { DemoHomePage } from "@/pages/DemoHomePage";
import { DependencyExplorerPage } from "@/pages/DependencyExplorerPage";
import { ExportCenterPage } from "@/pages/ExportCenterPage";
import { FindingsPage } from "@/pages/FindingsPage";
import { LicenceInventoryPage } from "@/pages/LicenceInventoryPage";
import { NewRepositoryPage } from "@/pages/NewRepositoryPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { OpenSSFPosturePage } from "@/pages/OpenSSFPosturePage";
import { ProviderHealthPage } from "@/pages/ProviderHealthPage";
import { RepositoriesPage } from "@/pages/RepositoriesPage";
import { RepositoryDetailsPage } from "@/pages/RepositoryDetailsPage";
import { ScanComparisonPage } from "@/pages/ScanComparisonPage";
import { ScanCompareSelectPage } from "@/pages/ScanCompareSelectPage";
import { ScanDetailsPage } from "@/pages/ScanDetailsPage";
import { ScansIndexPage } from "@/pages/ScansIndexPage";
import { UploadArchivePage } from "@/pages/UploadArchivePage";
import { VulnerabilityExplorerPage } from "@/pages/VulnerabilityExplorerPage";
import { WorkflowFindingsPage } from "@/pages/WorkflowFindingsPage";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/demo", element: <DemoHomePage /> },
      { path: "/about", element: <AboutPage /> },

      // Repositories
      { path: "/repositories", element: <RepositoriesPage /> },
      { path: "/repositories/new", element: <NewRepositoryPage /> },
      { path: "/repositories/upload", element: <UploadArchivePage /> },
      {
        path: "/repositories/:repositoryId",
        element: <RepositoryDetailsPage />,
      },

      // Scans
      { path: "/scans", element: <ScansIndexPage /> },
      { path: "/scans/:scanId", element: <ScanDetailsPage /> },
      {
        path: "/scans/:scanId/findings",
        element: <FindingsPage />,
      },
      {
        path: "/scans/:scanId/vulnerabilities",
        element: <VulnerabilityExplorerPage />,
      },
      {
        path: "/scans/:scanId/dependencies",
        element: <DependencyExplorerPage />,
      },
      {
        path: "/scans/:scanId/workflows",
        element: <WorkflowFindingsPage />,
      },
      {
        path: "/scans/:scanId/openssf",
        element: <OpenSSFPosturePage />,
      },
      {
        path: "/scans/:scanId/licences",
        element: <LicenceInventoryPage />,
      },
      {
        path: "/scans/:scanId/providers",
        element: <ProviderHealthPage />,
      },
      {
        path: "/scans/:scanId/exports",
        element: <ExportCenterPage />,
      },
      {
        path: "/scans/:scanId/compare-select",
        element: <ScanCompareSelectPage />,
      },
      {
        path: "/scans/:scanId/compare/:baseScanId",
        element: <ScanComparisonPage />,
      },

      // Providers
      { path: "/providers", element: <ProviderHealthPage /> },

      // Findings shortcut
      { path: "/findings", element: <Navigate to="/scans" replace /> },

      { path: "/404", element: <NotFoundPage /> },
      { path: "*", element: <Navigate to="/404" replace /> },
    ],
  },
]);

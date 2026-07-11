import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "@/layouts/AppShell";
import { AboutPage } from "@/pages/AboutPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { FindingsPage } from "@/pages/FindingsPage";
import { NewRepositoryPage } from "@/pages/NewRepositoryPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ProvidersPage } from "@/pages/ProvidersPage";
import { RepositoriesPage } from "@/pages/RepositoriesPage";
import { RepositoryDetailsPage } from "@/pages/RepositoryDetailsPage";
import { ScanDetailsPage } from "@/pages/ScanDetailsPage";
import { ScansIndexPage } from "@/pages/ScansIndexPage";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/about", element: <AboutPage /> },
      { path: "/repositories", element: <RepositoriesPage /> },
      { path: "/repositories/new", element: <NewRepositoryPage /> },
      {
        path: "/repositories/:repositoryId",
        element: <RepositoryDetailsPage />,
      },
      { path: "/scans", element: <ScansIndexPage /> },
      { path: "/scans/:scanId", element: <ScanDetailsPage /> },
      { path: "/scans/:scanId/findings", element: <FindingsPage /> },
      { path: "/scans/:scanId/providers", element: <ProvidersPage /> },
      { path: "/404", element: <NotFoundPage /> },
      { path: "*", element: <Navigate to="/404" replace /> },
    ],
  },
]);

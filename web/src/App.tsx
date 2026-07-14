import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuthStore } from "./stores/authStore";
import AppLayout from "./components/layout/AppLayout";
import { routerBasename, withBasePath } from "./lib/basePath";

const Login = lazy(() => import("./pages/Login"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Chat = lazy(() => import("./pages/Chat"));
const AgentPlayground = lazy(() => import("./pages/AgentPlayground"));
const Channels = lazy(() => import("./pages/Channels"));
const Tools = lazy(() => import("./pages/Tools"));
const CronJobs = lazy(() => import("./pages/CronJobs"));
const Settings = lazy(() => import("./pages/Settings"));
const Users = lazy(() => import("./pages/Users"));
const SystemConfig = lazy(() => import("./pages/SystemConfig"));
const TripBriefingPage = lazy(() => import("./pages/TripBriefingPage"));
const FeedbackPage = lazy(() => import("./pages/FeedbackPage"));
const SettingCheckChatPage = lazy(() => import("./pages/SettingCheckChatPage"));
const SettingCheckV2Page = lazy(() => import("./pages/SettingCheckV2Page"));
const FaultAnalysisPage = lazy(() => import("./pages/FaultAnalysisPage"));
const FaultAnalysisReportPage = lazy(() => import("./pages/FaultAnalysisReportPage"));

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { token, authlessEnabled } = useAuthStore((s) => ({
    token: s.token,
    authlessEnabled: s.authlessEnabled,
  }));
  return token || authlessEnabled ? <>{children}</> : <Navigate to="/login" replace />;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user, authlessEnabled } = useAuthStore((s) => ({
    user: s.user,
    authlessEnabled: s.authlessEnabled,
  }));
  if (authlessEnabled) return <Navigate to="/chat" replace />;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "admin") return <Navigate to="/chat" replace />;
  return <>{children}</>;
}

export default function App() {
  const { initialized, setBootstrap, markInitialized, token, authlessEnabled } = useAuthStore((s) => ({
    initialized: s.initialized,
    setBootstrap: s.setBootstrap,
    markInitialized: s.markInitialized,
    token: s.token,
    authlessEnabled: s.authlessEnabled,
  }));

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      try {
        const res = await fetch(withBasePath("/api/auth/bootstrap"), { credentials: "same-origin" });
        if (!res.ok) {
          throw new Error(`bootstrap failed: ${res.status}`);
        }
        const data = await res.json();
        if (cancelled) return;
        setBootstrap({
          authlessEnabled: Boolean(data.auth_disabled),
          initialized: true,
          user: data.user ?? null,
        });
      } catch {
        if (!cancelled) {
          markInitialized();
        }
      }
    };

    if (!initialized) {
      void bootstrap();
    }

    return () => {
      cancelled = true;
    };
  }, [initialized, markInitialized, setBootstrap]);

  if (!initialized) {
    return null;
  }

  if (routerBasename === "/agentplayground") {
    return (
      <Suspense fallback={null}>
        <Routes>
          <Route path="/" element={<AgentPlayground />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    );
  }

  const defaultPrivatePath = "/chat";

  return (
    <Suspense fallback={null}>
      <Routes>
      <Route
        path="/login"
        element={authlessEnabled || token ? <Navigate to={defaultPrivatePath} replace /> : <Login />}
      />
      <Route
        path="/"
        element={
          <PrivateRoute>
            <AppLayout />
          </PrivateRoute>
        }
      >
        <Route index element={<Navigate to={defaultPrivatePath} replace />} />
        <Route
          path="dashboard"
          element={<Dashboard />}
        />
        <Route path="chat" element={<Chat />} />
        <Route path="chat/:sessionKey" element={<Chat />} />
        <Route path="wave-record" element={<Chat />} />
        <Route path="setting-check" element={<Chat />} />
        <Route path="fault-analysis" element={<FaultAnalysisPage />} />
        <Route path="feedback" element={<FeedbackPage />} />
        <Route
          path="providers"
          element={<Navigate to={authlessEnabled ? "/chat" : "/settings?tab=providers"} replace />}
        />
        <Route
          path="channels"
          element={
            <AdminRoute>
              <Channels />
            </AdminRoute>
          }
        />
        <Route
          path="mcp"
          element={<Navigate to="/tools?tab=mcp" replace />}
        />
        <Route
          path="skills"
          element={<Navigate to="/tools?tab=skills" replace />}
        />
        <Route
          path="tools"
          element={
            <AdminRoute>
              <Tools />
            </AdminRoute>
          }
        />
        <Route
          path="cron"
          element={
            <AdminRoute>
              <CronJobs />
            </AdminRoute>
          }
        />
        <Route
          path="settings"
          element={
            <AdminRoute>
              <Settings />
            </AdminRoute>
          }
        />
        <Route
          path="users"
          element={
            <AdminRoute>
              <Users />
            </AdminRoute>
          }
        />
        <Route
          path="system-config"
          element={
            <AdminRoute>
              <SystemConfig />
            </AdminRoute>
          }
        />
      </Route>
      <Route
        path="agentplayground"
        element={<Navigate to="/chat" replace />}
      />
      <Route
        path="trip-briefing/:jobId"
        element={<TripBriefingPage />}
      />
      <Route
        path="fault-analysis/:jobId"
        element={<FaultAnalysisReportPage />}
      />
      <Route
        path="setting-check/:jobId"
        element={<SettingCheckChatPage />}
      />
      <Route
        path="setting-check-v2"
        element={<SettingCheckV2Page />}
      />
      <Route path="*" element={<Navigate to={defaultPrivatePath} replace />} />
    </Routes>
    </Suspense>
  );
}

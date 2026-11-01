import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';

// Global Context Providers
import { AuthProvider } from '../context/AuthContext';
import { ProfileProvider } from '../context/ProfileContext';

// Route Protection
import ProtectedRoute from './ProtectedRoute';
import AdminRoute from './AdminRoute';
import ProfileGate from './ProfileGate';

// Layout Components
import Sidebar from '../components/layout/Sidebar';
import Navbar from '../components/layout/Navbar';
import ActiveOpportunityBar from '../components/opportunities/ActiveOpportunityBar';
import RouteLoadingOverlay from '../components/common/RouteLoadingOverlay';
import RouteErrorBoundary from '../components/common/RouteErrorBoundary';
import Loader from '../components/common/Loader';

// Styles for every page, then the pages themselves, each loaded when first opened
import './pageStyles';

const Home = lazy(() => import('../pages/Home'));
const Login = lazy(() => import('../pages/Login'));
const Register = lazy(() => import('../pages/Register'));
const ForgotPassword = lazy(() => import('../pages/ForgotPassword'));
const ResetPassword = lazy(() => import('../pages/ResetPassword'));
const Dashboard = lazy(() => import('../pages/Dashboard'));
const Profile = lazy(() => import('../pages/Profile'));
const ProfileSetupChoice = lazy(() => import('../pages/ProfileSetupChoice'));
const CvUpload = lazy(() => import('../pages/CvUpload'));
const ProfileVerification = lazy(() => import('../pages/ProfileVerification'));
const ProfileCompleted = lazy(() => import('../pages/ProfileCompleted'));
const Documents = lazy(() => import('../pages/Documents'));
const Universities = lazy(() => import('../pages/Universities'));
const UniversityDetails = lazy(() => import('../pages/UniversityDetails'));
const Scholarships = lazy(() => import('../pages/Scholarships'));
const ScholarshipDetails = lazy(() => import('../pages/ScholarshipDetails'));
const SavedOpportunities = lazy(() => import('../pages/SavedOpportunities'));
const Compare = lazy(() => import('../pages/Compare'));
const FinancialFeasibility = lazy(() => import('../pages/FinancialFeasibility'));
const ApplicationPathway = lazy(() => import('../pages/ApplicationPathway'));
const Recommendations = lazy(() => import('../pages/Recommendations'));
const Timeline = lazy(() => import('../pages/Timeline'));
const ProfileImprovement = lazy(() => import('../pages/ProfileImprovement'));
const AdminScholarships = lazy(() => import('../pages/AdminScholarships'));
const AdminScholarshipEdit = lazy(() => import('../pages/AdminScholarshipEdit'));
const Settings = lazy(() => import('../pages/Settings'));
const Explore = lazy(() => import('../pages/Explore'));
const PathwayHub = lazy(() => import('../pages/PathwayHub'));

const ACTIVE_BAR_PATHS = ['/recommendations', '/financial', '/documents', '/timeline'];

export default function AppRoutes() {
  const { pathname } = useLocation();

  return (
    <AuthProvider>
      <ProfileProvider>
        <>
          <RouteErrorBoundary key={`public-${pathname}`}>
          <Suspense fallback={<Loader message="Loading page..." />}>
          <Routes>

          {/* =========================
              PUBLIC ROUTES
          ========================= */}

          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />


          {/* =========================
              PROTECTED APPLICATION
          ========================= */}

          <Route element={<ProtectedRoute />}>
            <Route
              path="/*"
              element={
                <div className="app-layout">

                  {/* Sidebar */}
                  <Sidebar />

                  {/* Main Content */}
                  <div className="main-content">

                    {/* Navbar */}
                    <Navbar />

                    <main className="app-container">
                      {ACTIVE_BAR_PATHS.includes(pathname.replace(/\/+$/, '')) && <ActiveOpportunityBar />}

                      <RouteErrorBoundary key={pathname}>
                      <Suspense fallback={<Loader message="Loading page..." />}>
                      <Routes>

                        {/* Profile Onboarding */}
                        <Route element={<ProfileGate gate="onboarding" />}>
                          <Route
                            path="/profile-setup"
                            element={<ProfileSetupChoice />}
                          />

                          <Route
                            path="/profile-setup/cv"
                            element={<CvUpload />}
                          />
                        </Route>


                        {/* Profile */}
                        <Route element={<ProfileGate gate="any" />}>
                          <Route
                            path="/profile/verify"
                            element={<ProfileVerification />}
                          />

                          <Route
                            path="/profile-setup/complete"
                            element={<ProfileCompleted />}
                          />

                          <Route
                            path="/profile"
                            element={<Profile />}
                          />
                        </Route>


                        {/* Administration */}
                        <Route element={<AdminRoute />}>
                          <Route path="/admin/scholarships" element={<AdminScholarships />} />
                          <Route path="/admin/scholarships/new" element={<AdminScholarshipEdit />} />
                          <Route path="/admin/scholarships/:id" element={<AdminScholarshipEdit />} />
                        </Route>


                        {/* Everything else needs a finished profile */}
                        <Route element={<ProfileGate gate="complete" />}>

                        {/* Dashboard */}
                        <Route
                          path="/dashboard"
                          element={<Dashboard />}
                        />


                        {/* Documents */}
                        <Route
                          path="/documents"
                          element={<Documents />}
                        />


                        {/* Universities */}
                        <Route
                          path="/universities"
                          element={<Explore><Universities /></Explore>}
                        />

                        <Route
                          path="/universities/:id"
                          element={<UniversityDetails />}
                        />


                        {/* Scholarships */}
                        <Route
                          path="/scholarships"
                          element={<Explore><Scholarships /></Explore>}
                        />

                        <Route
                          path="/scholarships/:id"
                          element={<ScholarshipDetails />}
                        />


                        {/* Decision Support */}
                        <Route
                          path="/saved"
                          element={<SavedOpportunities />}
                        />

                        <Route
                          path="/compare"
                          element={<Compare />}
                        />

                        <Route
                          path="/financial"
                          element={<FinancialFeasibility />}
                        />

                        <Route
                          path="/pathway"
                          element={<PathwayHub><ApplicationPathway /></PathwayHub>}
                        />

                        <Route
                          path="/recommendations"
                          element={<Explore><Recommendations /></Explore>}
                        />

                        <Route
                          path="/timeline"
                          element={<PathwayHub><Timeline /></PathwayHub>}
                        />

                        <Route
                          path="/improvement"
                          element={<ProfileImprovement />}
                        />

                        <Route
                          path="/settings"
                          element={<Settings />}
                        />


                        {/* Unknown protected route */}
                        <Route
                          path="*"
                          element={<Navigate to="/dashboard" replace />}
                        />

                        </Route>

                      </Routes>
                      </Suspense>
                      </RouteErrorBoundary>

                    </main>

                  </div>

                </div>
              }
            />
          </Route>

          </Routes>
          </Suspense>
          </RouteErrorBoundary>
          <RouteLoadingOverlay />
        </>
      </ProfileProvider>
    </AuthProvider>
  );
}
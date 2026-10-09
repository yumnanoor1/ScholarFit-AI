import { Routes, Route, Navigate } from 'react-router-dom';

// Global Context Providers
import { AuthProvider } from '../context/AuthContext';
import { ProfileProvider } from '../context/ProfileContext';

// Route Protection
import ProtectedRoute from './ProtectedRoute';

// Layout Components
import Sidebar from '../components/layout/Sidebar';
import Navbar from '../components/layout/Navbar';

// Public & Authentication Pages
import Home from '../pages/Home';
import Login from '../pages/Login';
import Register from '../pages/Register';

// Protected Application Pages
import Dashboard from '../pages/Dashboard';
import Profile from '../pages/Profile';
import ProfileSetupChoice from '../pages/ProfileSetupChoice';
import CvUpload from '../pages/CvUpload';
import ProfileVerification from '../pages/ProfileVerification';
import Documents from '../pages/Documents';
import Universities from '../pages/Universities';
import UniversityDetails from '../pages/UniversityDetails';
import Scholarships from '../pages/Scholarships';
import ScholarshipDetails from '../pages/ScholarshipDetails';
import SavedOpportunities from '../pages/SavedOpportunities';
import Compare from '../pages/Compare';
import FinancialFeasibility from '../pages/FinancialFeasibility';
import ApplicationPathway from '../pages/ApplicationPathway';
import Recommendations from '../pages/Recommendations';
import Timeline from '../pages/Timeline';
import ProfileImprovement from '../pages/ProfileImprovement';
import Settings from '../pages/Settings';

export default function AppRoutes() {
  return (
    <AuthProvider>
      <ProfileProvider>
        <Routes>

          {/* =========================
              PUBLIC ROUTES
          ========================= */}

          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />


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

                    <main
                      style={{
                        flex: 1,
                        paddingBottom: '30px',
                      }}
                    >

                      <Routes>

                        {/* Profile Onboarding */}
                        <Route
                          path="/profile-setup"
                          element={<ProfileSetupChoice />}
                        />

                        <Route
                          path="/profile-setup/cv"
                          element={<CvUpload />}
                        />

                        <Route
                          path="/profile/verify"
                          element={<ProfileVerification />}
                        />


                        {/* Dashboard */}
                        <Route
                          path="/dashboard"
                          element={<Dashboard />}
                        />


                        {/* Profile */}
                        <Route
                          path="/profile"
                          element={<Profile />}
                        />


                        {/* Documents */}
                        <Route
                          path="/documents"
                          element={<Documents />}
                        />


                        {/* Universities */}
                        <Route
                          path="/universities"
                          element={<Universities />}
                        />

                        <Route
                          path="/universities/:id"
                          element={<UniversityDetails />}
                        />


                        {/* Scholarships */}
                        <Route
                          path="/scholarships"
                          element={<Scholarships />}
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
                          element={<ApplicationPathway />}
                        />

                        <Route
                          path="/recommendations"
                          element={<Recommendations />}
                        />

                        <Route
                          path="/timeline"
                          element={<Timeline />}
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

                      </Routes>

                    </main>

                  </div>
                </div>
              }
            />
          </Route>

        </Routes>
      </ProfileProvider>
    </AuthProvider>
  );
}
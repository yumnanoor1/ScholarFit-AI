import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';

// Global Context Providers
import { AuthProvider } from '../context/AuthContext';
import { ProfileProvider } from '../context/ProfileContext';

// Layout Components
import Sidebar from '../components/layout/Sidebar';
import Navbar from '../components/layout/Navbar';
import Footer from '../components/layout/Footer';

// Public & Authentication Pages
import Home from '../pages/Home';
import Login from '../pages/Login';
import Register from '../pages/Register';

// Protected Application Pages
import Dashboard from '../pages/Dashboard';
import Profile from '../pages/Profile';
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
          {/* Public Routes */}
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />

          {/* Protected Application Layout */}
          <Route
            path="/*"
            element={
              <div className="app-layout">
                {/* Fixed Sidebar Navigation */}
                <Sidebar />

                {/* Main Content View Container */}
                <div className="main-content">
                  <Navbar />
                  
                  <main style={{ flex: 1, paddingBottom: '30px' }}>
                    <Routes>
                      <Route path="/dashboard" element={<Dashboard />} />
                      <Route path="/profile" element={<Profile />} />
                      <Route path="/documents" element={<Documents />} />
                      
                      {/* University & Admission Matching */}
                      <Route path="/universities" element={<Universities />} />
                      <Route path="/universities/:id" element={<UniversityDetails />} />
                      
                      {/* Scholarship & Funding Matching */}
                      <Route path="/scholarships" element={<Scholarships />} />
                      <Route path="/scholarships/:id" element={<ScholarshipDetails />} />
                      
                      {/* Decision Support Tools */}
                      <Route path="/saved" element={<SavedOpportunities />} />
                      <Route path="/compare" element={<Compare />} />
                      <Route path="/financial" element={<FinancialFeasibility />} />
                      <Route path="/pathway" element={<ApplicationPathway />} />
                      <Route path="/recommendations" element={<Recommendations />} />
                      <Route path="/timeline" element={<Timeline />} />
                      <Route path="/improvement" element={<ProfileImprovement />} />
                      <Route path="/settings" element={<Settings />} />
                      
                      {/* Fallback Redirect */}
                      <Route path="*" element={<Navigate to="/dashboard" replace />} />
                    </Routes>
                  </main>

                  <Footer />
                </div>
              </div>
            }
          />
        </Routes>
      </ProfileProvider>
    </AuthProvider>
  );
}
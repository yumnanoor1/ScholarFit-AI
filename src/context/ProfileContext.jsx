import React, { createContext, useContext, useState, useEffect } from 'react';

const ProfileContext = createContext(null);

const DEFAULT_PROFILE = {
  name: "Alexander Wright",
  degree: "BS Computer Science",
  degreeLevel: "Bachelor's",
  university: "National University of Sciences",
  cgpa: "3.65",
  graduationYear: "2024",
  englishTest: "IELTS",
  englishScore: "7.5",
  skills: ["Python", "Machine Learning", "Data Structures", "FastAPI", "React.js"],
  projects: ["AI Image Classifier", "Automated Grading System"],
  researchExperience: "Co-authored 1 conference paper on NLP for healthcare domain.",
  fieldOfInterest: "Computer Science & AI",
  preferredCountries: ["Germany", "United States", "Canada"],
  preferredDegree: "Master's",
  fundingPreference: "Full Funding Required",
  approximateBudget: "$5,000 / year",
  profileCompletionPercentage: 85
};

export function ProfileProvider({ children }) {
  const [profile, setProfile] = useState(DEFAULT_PROFILE);
  const [savedOpportunities, setSavedOpportunities] = useState(["univ-1", "sch-1"]);
  const [loading, setLoading] = useState(false);

  // Helper calculation for profile completion
  const calculateCompleteness = (data) => {
    const fields = [
      'name', 'degree', 'university', 'cgpa', 'englishTest', 
      'englishScore', 'fieldOfInterest', 'fundingPreference'
    ];
    let filled = 0;
    fields.forEach(field => {
      if (data[field] && String(data[field]).trim() !== '') filled++;
    });
    return Math.round((filled / fields.length) * 100);
  };

  const updateProfile = async (updatedData) => {
    setLoading(true);
    return new Promise((resolve) => {
      setTimeout(() => {
        const newCompleteness = calculateCompleteness(updatedData);
        const finalProfile = {
          ...profile,
          ...updatedData,
          profileCompletionPercentage: newCompleteness
        };
        setProfile(finalProfile);
        setLoading(false);
        resolve({ success: true, profile: finalProfile });
      }, 400);
    });
  };

  const toggleSaveOpportunity = (id) => {
    setSavedOpportunities((prev) => {
      if (prev.includes(id)) {
        return prev.filter(savedId => savedId !== id);
      } else {
        return [...prev, id];
      }
    });
  };

  const isOpportunitySaved = (id) => {
    return savedOpportunities.includes(id);
  };

  return (
    <ProfileContext.Provider value={{
      profile,
      loading,
      updateProfile,
      savedOpportunities,
      toggleSaveOpportunity,
      isOpportunitySaved
    }}>
      {children}
    </ProfileContext.Provider>
  );
}

export function useProfile() {
  const context = useContext(ProfileContext);
  if (!context) {
    throw new Error('useProfile must be used within a ProfileProvider');
  }
  return context;
}
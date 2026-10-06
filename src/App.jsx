import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppRoutes from "./navigation/AppRoutes";
import { BackgroundPaths } from "./components/ui/background-paths";
import "./styles/global.css";

export default function App() {
  const [showSplash, setShowSplash] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const splashTimer = window.setTimeout(() => setShowSplash(false), 2400);
    return () => window.clearTimeout(splashTimer);
  }, []);

  if (showSplash) {
    return (
      <BackgroundPaths 
        title="FitScholar AI" 
        onExplore={() => setShowSplash(false)} 
        onLogin={() => {
          setShowSplash(false);
          navigate('/login');
        }}
        onRegister={() => {
          setShowSplash(false);
          navigate('/register');
        }}
      />
    );
  }

  return <AppRoutes />;
}
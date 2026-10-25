import { useState } from "react";
import { useLocation } from "react-router-dom";
import AppRoutes from "./navigation/AppRoutes";
import { BackgroundPaths } from "./components/ui/background-paths";
import "./styles/global.css";
import "./styles/cards.css";
import "./styles/forms.css";
import "./styles/sidebar.css";
import "./styles/navbar.css";
import "./styles/responsive.css";
import "./styles/profile-wizard.css";

export default function App() {
  const location = useLocation();
  const [showSplash, setShowSplash] = useState(true);

  if (showSplash && location.pathname === "/") {
    return (
      <BackgroundPaths 
        onExplore={() => setShowSplash(false)} 
        onVideoEnded={() => setShowSplash(false)}
      />
    );
  }

  return <AppRoutes />;
}
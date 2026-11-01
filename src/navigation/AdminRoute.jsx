import { Link, Outlet } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/** Keeps the admin pages out of students' way. The real check is on every backend request. */
export default function AdminRoute() {
  const { user } = useAuth();
  if (user?.role !== 'admin') {
    return (
      <div className="page-container" role="alert">
        <h1>Administrators only</h1>
        <p>Your account doesn't have access to this page.</p>
        <Link to="/dashboard">Back to your dashboard</Link>
      </div>
    );
  }
  return <Outlet />;
}

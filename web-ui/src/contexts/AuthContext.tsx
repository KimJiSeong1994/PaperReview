import { createContext, useContext, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { verifyToken } from '../api/client';

interface AuthContextValue {
  isAuthenticated: boolean;
  userRole: string;
  showLoginModal: boolean;
  setShowLoginModal: (show: boolean) => void;
  login: () => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();

  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(
    () => !!localStorage.getItem('access_token')
  );
  const [userRole, setUserRole] = useState<string>(
    () => localStorage.getItem('user_role') || 'user'
  );
  const [showLoginModal, setShowLoginModal] = useState(false);

  // Verify token on mount
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      verifyToken(token)
        .then((data) => {
          setIsAuthenticated(true);
          setUserRole(data.role || 'user');
          localStorage.setItem('user_role', data.role || 'user');
        })
        .catch(() => {
          localStorage.removeItem('access_token');
          localStorage.removeItem('username');
          localStorage.removeItem('user_role');
          setIsAuthenticated(false);
          setUserRole('user');
        });
    }
  }, []);

  // Listen for forced logout from API interceptor (e.g. expired/invalid token)
  useEffect(() => {
    const handleForceLogout = () => {
      setIsAuthenticated(false);
      setUserRole('user');
      setShowLoginModal(true);
    };
    window.addEventListener('auth:logout', handleForceLogout);
    return () => window.removeEventListener('auth:logout', handleForceLogout);
  }, []);

  const login = () => {
    setIsAuthenticated(true);
    const role = localStorage.getItem('user_role') || 'user';
    setUserRole(role);
    setShowLoginModal(false);
    navigate('/mypage');
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('username');
    localStorage.removeItem('user_role');
    setIsAuthenticated(false);
    setUserRole('user');
    navigate('/');
  };

  return (
    <AuthContext.Provider
      value={{ isAuthenticated, userRole, showLoginModal, setShowLoginModal, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

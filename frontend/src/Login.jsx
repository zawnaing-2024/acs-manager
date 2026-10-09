import React, { useState } from 'react';
import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap-icons/font/bootstrap-icons.css';

const Login = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('Please enter both username and password.');
      return;
    }

    setLoading(true);
    setError('');

    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    try {
      const response = await fetch('http://127.0.0.1:8000/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData,
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Login failed.');
      }

      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify({ username: data.username, full_name: data.full_name }));

      onLoginSuccess(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ backgroundColor: '#0f172a', minHeight: '100vh' }} className="d-flex flex-column align-items-center justify-content-center px-3">
      <div className="card border-0 shadow-lg rounded-4 overflow-hidden" style={{ maxWidth: '420px', width: '100%', backgroundColor: '#1e293b' }}>
        <div className="card-body p-4 p-sm-5">
          <div className="text-center mb-4">
            <div className="bg-primary bg-opacity-20 text-primary d-inline-flex p-3 rounded-circle mb-3">
              <i className="bi bi-router-fill fs-1"></i>
            </div>
            <h3 className="fw-bold text-white mb-1">ACS Manager v1</h3>
            <p className="text-muted small mb-0">ISP Network Operations Gateway</p>
          </div>

          {error && (
            <div className="alert alert-danger border-0 rounded-3 small py-2 px-3 mb-4 d-flex align-items-center">
              <i className="bi bi-exclamation-triangle-fill me-2"></i>
              <div>{error}</div>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="mb-3">
              <label className="form-label text-light small fw-semibold">Username</label>
              <div className="input-group">
                <span className="input-group-text bg-dark border-secondary text-muted">
                  <i className="bi bi-person-fill"></i>
                </span>
                <input
                  type="text"
                  className="form-control bg-dark border-secondary text-white shadow-none"
                  placeholder="Enter username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
            </div>

            <div className="mb-4">
              <label className="form-label text-light small fw-semibold">Password</label>
              <div className="input-group">
                <span className="input-group-text bg-dark border-secondary text-muted">
                  <i className="bi bi-key-fill"></i>
                </span>
                <input
                  type={showPassword ? 'text' : 'password'}
                  className="form-control bg-dark border-secondary text-white shadow-none"
                  placeholder="Enter password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  className="btn btn-outline-secondary border-secondary text-muted"
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                >
                  <i className={`bi bi-eye${showPassword ? '-slash' : ''}`}></i>
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary w-100 py-2.5 fw-semibold rounded-3 shadow-sm mb-3"
              disabled={loading}
            >
              {loading ? (
                <>
                  <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                  Authenticating...
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </form>

          <div className="text-center pt-2 border-top border-secondary border-opacity-25">
            <span className="text-secondary small fw-medium">Authorized by ZN</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Login;
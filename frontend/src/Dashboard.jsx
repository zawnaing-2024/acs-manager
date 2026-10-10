import React, { useState, useEffect } from 'react';
import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap-icons/font/bootstrap-icons.css';

const Dashboard = ({ user, onLogout }) => {
  const [onus, setOnus] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Search State
  const [searchTerm, setSearchTerm] = useState('');

  // Details Modal States
  const [showModal, setShowModal] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState(null);
  const [wifiData, setWifiData] = useState(null);
  const [wanData, setWanData] = useState(null);
  const [hostsData, setHostsData] = useState(null);

  // Editable Wi-Fi & Password Visibility
  const [editSsid, setEditSsid] = useState('');
  const [editPassword, setEditPassword] = useState('');
  const [showWifiPassword, setShowWifiPassword] = useState(false);
  const [saveWifiLoading, setSaveWifiLoading] = useState(false);

  // Diagnostics Modal States
  const [showDiagModal, setShowDiagModal] = useState(false);
  const [diagDevice, setDiagDevice] = useState(null);
  const [diagType, setDiagType] = useState('ping');
  const [targetHost, setTargetHost] = useState('8.8.8.8');
  const [diagLoading, setDiagLoading] = useState(false);
  const [pingResult, setPingResult] = useState(null);
  const [traceResult, setTraceResult] = useState(null);
  const [diagError, setDiagError] = useState(null);

  const getAuthHeaders = () => {
    const token = localStorage.getItem('token');
    return {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/json',
      'Content-Type': 'application/json'
    };
  };

  const handleAuthError = (res) => {
    if (res.status === 401) {
      alert("Session expired or unauthorized. Please log in again.");
      if (onLogout) onLogout();
      return true;
    }
    return false;
  };

  const fetchOnus = async (showSpinner = true) => {
    if (showSpinner) setLoading(true);
    setError(null);
    try {
      const response = await fetch('http://127.0.0.1:8000/api/v1/onus', {
        headers: getAuthHeaders()
      });

      if (handleAuthError(response)) return;
      if (!response.ok) throw new Error(`Failed to fetch: ${response.statusText}`);

      const data = await response.json();
      setOnus(data);
    } catch (err) {
      setError(err.message);
    } finally {
      if (showSpinner) setLoading(false);
    }
  };

  useEffect(() => {
    fetchOnus(true);
    const intervalId = setInterval(() => fetchOnus(false), 5000);
    return () => clearInterval(intervalId);
  }, []);

  const handleOpenDiagnostics = (deviceId, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setDiagDevice(deviceId);
    setShowDiagModal(true);
    setPingResult(null);
    setTraceResult(null);
    setDiagError(null);
  };

  const handleRunDiagnostic = async () => {
    if (!targetHost.trim()) {
      alert("Please enter a destination IP or hostname.");
      return;
    }

    setDiagLoading(true);
    setDiagError(null);
    setPingResult(null);
    setTraceResult(null);

    const encodedId = encodeURIComponent(encodeURIComponent(diagDevice));
    const endpoint = diagType === 'ping' 
      ? `http://127.0.0.1:8000/api/v1/onus/${encodedId}/diagnostics/ping`
      : `http://127.0.0.1:8000/api/v1/onus/${encodedId}/diagnostics/traceroute`;

    const bodyData = diagType === 'ping' 
      ? JSON.stringify({ host: targetHost, count: 4 })
      : JSON.stringify({ host: targetHost });

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: bodyData
      });

      if (handleAuthError(res)) return;
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Diagnostic operation failed.');

      if (diagType === 'ping') {
        setPingResult(data);
      } else {
        setTraceResult(data);
      }
    } catch (err) {
      setDiagError(err.message);
    } finally {
      setDiagLoading(false);
    }
  };

  const handleReboot = async (deviceId, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (!window.confirm(`Are you sure you want to REBOOT device ${deviceId}?`)) return;

    try {
      const response = await fetch(`http://127.0.0.1:8000/api/v1/onus/${encodeURIComponent(encodeURIComponent(deviceId))}/reboot`, {
        method: 'POST',
        headers: getAuthHeaders()
      });

      if (handleAuthError(response)) return;
      const responseData = await response.json();
      if (!response.ok) throw new Error(responseData.detail || 'Reboot command failed');

      alert(`Reboot command sent successfully to ${deviceId}.`);
      fetchOnus(false);
    } catch (err) {
      alert(`Error rebooting device: ${err.message}`);
    }
  };

  const handleDelete = async (deviceId, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (!window.confirm(`WARNING: Are you sure you want to DELETE device ${deviceId}?`)) return;

    try {
      setOnus((prevOnus) => prevOnus.filter((onu) => onu.device_id !== deviceId));
      const response = await fetch(`http://127.0.0.1:8000/api/v1/onus/${encodeURIComponent(encodeURIComponent(deviceId))}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
      });

      if (handleAuthError(response)) return;
      const responseData = await response.json();
      if (!response.ok) throw new Error(responseData.detail || 'Delete command failed');

      alert(`Device ${deviceId} successfully deleted.`);
      fetchOnus(false);
    } catch (err) {
      alert(`Error deleting device: ${err.message}`);
      fetchOnus(true);
    }
  };

  const handleViewDetails = async (deviceId, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setSelectedDevice(deviceId);
    setShowModal(true);
    setDetailsLoading(true);
    setDetailsError(null);
    setWifiData(null);
    setWanData(null);
    setHostsData(null);
    setShowWifiPassword(false);

    try {
      const encodedId = encodeURIComponent(encodeURIComponent(deviceId));
      const headers = getAuthHeaders();

      const [wifiRes, wanRes, hostsRes] = await Promise.all([
        fetch(`http://127.0.0.1:8000/api/v1/onus/${encodedId}/wifi`, { headers }),
        fetch(`http://127.0.0.1:8000/api/v1/onus/${encodedId}/wan`, { headers }),
        fetch(`http://127.0.0.1:8000/api/v1/onus/${encodedId}/hosts`, { headers })
      ]);

      if (handleAuthError(wifiRes) || handleAuthError(wanRes) || handleAuthError(hostsRes)) return;

      if (!wifiRes.ok) throw new Error("Failed to fetch Wi-Fi settings");
      if (!wanRes.ok) throw new Error("Failed to fetch WAN settings");
      if (!hostsRes.ok) throw new Error("Failed to fetch LAN hosts");

      const wifiJson = await wifiRes.json();
      setWifiData(wifiJson);
      setEditSsid(wifiJson.ssid || '');
      setEditPassword(wifiJson.password === 'N/A' ? '' : wifiJson.password || '');

      setWanData(await wanRes.json());
      setHostsData(await hostsRes.json());
    } catch (err) {
      setDetailsError(err.message);
    } finally {
      setDetailsLoading(false);
    }
  };

  const handleSaveWifi = async () => {
    if (!editSsid.trim() || !editPassword.trim()) {
      alert("SSID and Password cannot be empty.");
      return;
    }

    setSaveWifiLoading(true);
    try {
      const safeDeviceId = encodeURIComponent(encodeURIComponent(selectedDevice));
      const res = await fetch(`http://127.0.0.1:8000/api/v1/onus/${safeDeviceId}/wifi`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({ ssid: editSsid, password: editPassword })
      });

      if (handleAuthError(res)) return;
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to update Wi-Fi');

      alert("Wi-Fi SSID and Password updated successfully on the router!");
      setWifiData(prev => ({ ...prev, ssid: editSsid, password: editPassword }));
      setEditSsid(editSsid);
      setEditPassword(editPassword);
      setShowWifiPassword(true);
    } catch (err) {
      alert(`Error updating Wi-Fi: ${err.message}`);
    } finally {
      setSaveWifiLoading(false);
    }
  };

  const closeModal = () => {
    setShowModal(false);
    setSelectedDevice(null);
  };

  const filteredOnus = onus.filter(onu => {
    const term = searchTerm.toLowerCase();
    return (
      (onu.serial_number && onu.serial_number.toLowerCase().includes(term)) ||
      (onu.ip_address && onu.ip_address.toLowerCase().includes(term)) ||
      (onu.mac_address && onu.mac_address.toLowerCase().includes(term)) ||
      (onu.pppoe_username && onu.pppoe_username.toLowerCase().includes(term)) ||
      (onu.device_id && onu.device_id.toLowerCase().includes(term)) ||
      (onu.status && onu.status.toLowerCase().includes(term))
    );
  });

  const totalOnus = onus.length;
  const onlineOnus = onus.filter(onu => onu.status === 'Online').length;
  const offlineOnus = onus.filter(onu => onu.status === 'Offline').length;

  return (
    <div className="d-flex flex-column" style={{ backgroundColor: '#f4f6f8', minHeight: '100vh' }}>
      {/* Header Navbar */}
      <nav className="navbar navbar-expand-lg navbar-dark bg-dark shadow-sm py-3">
        <div className="container-fluid px-4">
          <a className="navbar-brand fw-bold d-flex align-items-center" href="#!">
            <i className="bi bi-router-fill text-primary me-2 fs-4"></i>
            <span>ACS Manager <span className="badge bg-primary text-white fs-6 ms-1 px-2 py-1">v1</span></span>
          </a>
          <div className="d-flex align-items-center gap-3">
            <span className="text-light small">
              <i className="bi bi-person-circle me-1 text-primary"></i> 
              {user?.full_name || user?.username || 'Administrator'}
            </span>
            <button 
              className="btn btn-outline-danger btn-sm rounded-pill px-3"
              onClick={onLogout}
            >
              <i className="bi bi-box-arrow-right me-1"></i> Logout
            </button>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <div className="container-fluid px-4 my-4 flex-grow-1">
        {/* KPI Cards */}
        <div className="row g-4 mb-4">
          <div className="col-md-4">
            <div className="card bg-white border-0 shadow-sm rounded-4 h-100">
              <div className="card-body d-flex align-items-center">
                <div className="bg-primary bg-opacity-10 p-3 rounded-circle me-3 text-primary">
                  <i className="bi bi-hdd-network fs-3"></i>
                </div>
                <div>
                  <h6 className="text-muted mb-1">Total ONUs</h6>
                  <h3 className="mb-0 fw-bold">{loading ? '...' : totalOnus}</h3>
                </div>
              </div>
            </div>
          </div>
          <div className="col-md-4">
            <div className="card bg-white border-0 shadow-sm rounded-4 h-100">
              <div className="card-body d-flex align-items-center">
                <div className="bg-success bg-opacity-10 p-3 rounded-circle me-3 text-success">
                  <i className="bi bi-check-circle fs-3"></i>
                </div>
                <div>
                  <h6 className="text-muted mb-1">Online Devices</h6>
                  <h3 className="mb-0 fw-bold">{loading ? '...' : onlineOnus}</h3>
                </div>
              </div>
            </div>
          </div>
          <div className="col-md-4">
            <div className="card bg-white border-0 shadow-sm rounded-4 h-100">
              <div className="card-body d-flex align-items-center">
                <div className="bg-danger bg-opacity-10 p-3 rounded-circle me-3 text-danger">
                  <i className="bi bi-x-circle fs-3"></i>
                </div>
                <div>
                  <h6 className="text-muted mb-1">Offline Devices</h6>
                  <h3 className="mb-0 fw-bold">{loading ? '...' : offlineOnus}</h3>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ONU Table */}
        <div className="card border-0 shadow-sm rounded-4 p-4">
          <div className="d-flex justify-content-between align-items-center mb-4 flex-wrap gap-3">
            <h5 className="mb-0 fw-bold text-dark"><i className="bi bi-list-ul me-2"></i> Managed Devices</h5>
            <div className="input-group shadow-sm" style={{ maxWidth: '350px' }}>
              <span className="input-group-text bg-white border-end-0 text-muted">
                <i className="bi bi-search"></i>
              </span>
              <input 
                type="text" 
                className="form-control border-start-0 ps-0" 
                placeholder="Search by SN, IP, PPPoE..." 
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>
          </div>

          {error && <div className="alert alert-danger rounded-3">{error}</div>}

          <div className="table-responsive">
            <table className="table table-hover align-middle border-top">
              <thead className="table-light">
                <tr>
                  <th className="text-muted fw-semibold">Status</th>
                  <th className="text-muted fw-semibold">PPPoE User</th>
                  <th className="text-muted fw-semibold">Serial Number</th>
                  <th className="text-muted fw-semibold">IP Address</th>
                  <th className="text-muted fw-semibold">Uptime</th>
                  <th className="text-muted fw-semibold">Rx / Tx (dBm)</th>
                  <th className="text-muted fw-semibold">CPU / RAM</th>
                  <th className="text-muted fw-semibold text-center">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && onus.length === 0 ? (
                  <tr><td colSpan="8" className="text-center text-muted py-5">Loading data...</td></tr>
                ) : filteredOnus.length === 0 ? (
                  <tr>
                    <td colSpan="8" className="text-center text-muted py-5">
                      <i className="bi bi-search mb-2 fs-3 d-block text-black-50"></i>
                      No ONUs matched your search.
                    </td>
                  </tr>
                ) : (
                  filteredOnus.map((onu) => (
                    <tr key={onu.device_id}>
                      <td>
                        <span className={`badge rounded-pill bg-${onu.status === 'Online' ? 'success' : 'danger'} bg-opacity-10 text-${onu.status === 'Online' ? 'success' : 'danger'} border border-${onu.status === 'Online' ? 'success' : 'danger'}`}>
                          {onu.status}
                        </span>
                      </td>
                      <td><span className="fw-semibold text-primary">{onu.pppoe_username || 'None'}</span></td>
                      <td>
                        <div className="fw-bold text-dark">{onu.serial_number}</div>
                        <div className="text-muted small">{onu.model}</div>
                      </td>
                      <td className="font-monospace text-secondary small">{onu.ip_address}</td>
                      <td><span className="text-secondary fw-semibold small"><i className="bi bi-clock-history me-1 opacity-50"></i>{onu.uptime}</span></td>
                      <td>
                        <span className={onu.optical_power_rx < -27 ? 'text-danger fw-bold' : 'text-success fw-semibold'}>
                          {onu.optical_power_rx}
                        </span> 
                        <span className="text-muted"> / {onu.optical_power_tx}</span>
                      </td>
                      <td>
                        <div className="small">
                          <div>CPU: <span className="fw-semibold">{onu.cpu_usage}</span></div>
                          <div>RAM: <span className="fw-semibold">{onu.ram_usage}</span></div>
                        </div>
                      </td>
                      <td className="text-center">
                        <div className="btn-group shadow-sm">
                          <button 
                            type="button"
                            className="btn btn-sm btn-light border text-primary" 
                            title="View Details & Update Wi-Fi"
                            onClick={(e) => handleViewDetails(onu.device_id, e)}
                          >
                            <i className="bi bi-info-circle fw-bold"></i>
                          </button>

                          <button 
                            type="button"
                            className="btn btn-sm btn-light border text-info" 
                            title="Network Diagnostics (Ping/Traceroute)"
                            onClick={(e) => handleOpenDiagnostics(onu.device_id, e)}
                          >
                            <i className="bi bi-activity fw-bold"></i>
                          </button>

                          <button 
                            type="button"
                            className="btn btn-sm btn-light border text-warning" 
                            title="Reboot ONU"
                            onClick={(e) => handleReboot(onu.device_id, e)}
                          >
                            <i className="bi bi-arrow-clockwise fw-bold"></i>
                          </button>

                          <button 
                            type="button"
                            className="btn btn-sm btn-light border text-danger" 
                            title="Delete ONU"
                            onClick={(e) => handleDelete(onu.device_id, e)}
                          >
                            <i className="bi bi-trash fw-bold"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Diagnostics Modal */}
      {showDiagModal && (
        <>
          <div className="modal fade show" style={{ display: 'block' }} tabIndex="-1">
            <div className="modal-dialog modal-lg modal-dialog-centered">
              <div className="modal-content border-0 shadow-lg rounded-4 overflow-hidden">
                <div className="modal-header bg-dark text-white p-4">
                  <div>
                    <h5 className="modal-title fw-bold mb-0">
                      <i className="bi bi-activity text-info me-2"></i> ONU Network Diagnostics
                    </h5>
                    <small className="text-muted font-monospace">{diagDevice}</small>
                  </div>
                  <button type="button" className="btn-close btn-close-white" onClick={() => setShowDiagModal(false)}></button>
                </div>

                <div className="modal-body p-4 bg-light">
                  <div className="card border-0 shadow-sm rounded-4 p-3 mb-4 bg-white">
                    <div className="row g-3 align-items-center">
                      <div className="col-md-3">
                        <label className="form-label fw-semibold text-muted small mb-1">Diagnostic Mode</label>
                        <select 
                          className="form-select"
                          value={diagType} 
                          onChange={(e) => setDiagType(e.target.value)}
                        >
                          <option value="ping">Ping</option>
                          <option value="traceroute">Traceroute</option>
                        </select>
                      </div>

                      <div className="col-md-6">
                        <label className="form-label fw-semibold text-muted small mb-1">Destination Host / IP</label>
                        <input 
                          type="text" 
                          className="form-control font-monospace" 
                          placeholder="e.g. 8.8.8.8 or 1.1.1.1"
                          value={targetHost}
                          onChange={(e) => setTargetHost(e.target.value)}
                        />
                      </div>

                      <div className="col-md-3 d-flex align-items-end">
                        <button 
                          className="btn btn-primary w-100 fw-semibold rounded-3 mt-4 mt-md-0"
                          onClick={handleRunDiagnostic}
                          disabled={diagLoading}
                        >
                          {diagLoading ? (
                            <>
                              <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                              Running...
                            </>
                          ) : (
                            <>
                              <i className="bi bi-play-fill me-1"></i> Start Test
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </div>

                  {diagError && (
                    <div className="alert alert-danger rounded-3 mb-4">
                      <i className="bi bi-exclamation-triangle-fill me-2"></i> {diagError}
                    </div>
                  )}

                  {pingResult && (
                    <div className="card border-0 shadow-sm rounded-4 p-4 bg-white">
                      <h6 className="fw-bold border-bottom pb-2 mb-3 text-primary d-flex justify-content-between align-items-center">
                        <span><i className="bi bi-terminal-fill me-2"></i> ONU Ping Console</span>
                        <span className={`badge rounded-pill bg-${pingResult.packets_lost === 0 ? 'success' : 'danger'}`}>
                          {pingResult.packets_lost === 0 ? '0% Packet Loss' : `${pingResult.packets_lost} Packets Lost`}
                        </span>
                      </h6>

                      {/* Terminal Output Console */}
                      <div 
                        className="p-3 rounded-3 font-monospace small shadow-inner" 
                        style={{ 
                          backgroundColor: '#0d1117', 
                          color: '#39ff14', 
                          minHeight: '180px', 
                          whiteSpace: 'pre-wrap', 
                          lineHeight: '1.5' 
                        }}
                      >
                        {pingResult.terminal_output || `PING ${pingResult.host} statistics:\nSent: ${pingResult.packets_sent}, Received: ${pingResult.packets_received}`}
                      </div>
                    </div>
                  )}

                  {traceResult && (
                    <div className="card border-0 shadow-sm rounded-4 p-4 bg-white">
                      <h6 className="fw-bold border-bottom pb-2 mb-3 text-primary d-flex justify-content-between align-items-center">
                        <span><i className="bi bi-signpost-split me-2"></i> Traceroute Results</span>
                        <span className="badge bg-primary rounded-pill px-3 py-2">{traceResult.total_hops} Hops Completed</span>
                      </h6>
                      
                      <div className="mb-3 small text-muted font-monospace bg-dark p-2 rounded-3" style={{ color: '#00ff66' }}>
                        Diagnostics State: {traceResult.status}
                      </div>

                      <div className="table-responsive">
                        <table className="table table-sm table-hover align-middle small font-monospace mb-0">
                          <thead className="table-light">
                            <tr>
                              <th style={{ width: '80px' }}>Hop</th>
                              <th>IP Address / Host</th>
                              <th>RTT (ms)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {traceResult.hops.length === 0 ? (
                              <tr>
                                <td colSpan="3" className="text-center text-muted py-4">
                                  <i className="bi bi-exclamation-circle text-warning fs-5 d-block mb-1"></i>
                                  No hops returned yet (State: {traceResult.status}). Try testing again.
                                </td>
                              </tr>
                            ) : (
                              traceResult.hops.map((h) => (
                                <tr key={h.hop_number}>
                                  <td className="fw-bold text-primary">#{h.hop_number}</td>
                                  <td>
                                    {h.host_address === '*' || !h.host_address ? (
                                      <span className="text-muted fst-italic">* Request timed out</span>
                                    ) : (
                                      <span className="fw-semibold text-dark">{h.host_address}</span>
                                    )}
                                  </td>
                                  <td>
                                    {h.rtt_ms === '*' || !h.rtt_ms ? (
                                      <span className="badge bg-light text-muted border">*</span>
                                    ) : (
                                      <span className="badge bg-light text-dark border px-2 py-1">{h.rtt_ms} ms</span>
                                    )}
                                  </td>
                                </tr>
                              ))
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>

                <div className="modal-footer bg-white border-top p-3">
                  <button type="button" className="btn btn-light rounded-pill px-4" onClick={() => setShowDiagModal(false)}>Close</button>
                </div>
              </div>
            </div>
          </div>
          <div className="modal-backdrop fade show" onClick={() => setShowDiagModal(false)}></div>
        </>
      )}

      {/* Details & Wi-Fi Modal */}
      {showModal && (
        <>
          <div className="modal fade show" style={{ display: 'block' }} tabIndex="-1">
            <div className="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">
              <div className="modal-content border-0 shadow-lg rounded-4 overflow-hidden">
                <div className="modal-header bg-white border-bottom p-4">
                  <div>
                    <h4 className="modal-title fw-bold text-dark mb-1">Device Information</h4>
                    <p className="text-muted small mb-0 font-monospace">ID: {selectedDevice}</p>
                  </div>
                  <button type="button" className="btn-close shadow-none" onClick={closeModal}></button>
                </div>

                <div className="modal-body bg-light p-4">
                  {detailsLoading ? (
                    <div className="d-flex flex-column align-items-center justify-content-center py-5">
                      <div className="spinner-border text-primary mb-3" style={{ width: '3rem', height: '3rem' }} role="status"></div>
                      <h5 className="text-dark fw-semibold">Fetching Live Data</h5>
                      <p className="text-muted">Contacting physical router... (~3 seconds)</p>
                    </div>
                  ) : detailsError ? (
                    <div className="alert alert-danger rounded-3 d-flex align-items-center p-4">
                      <i className="bi bi-exclamation-triangle-fill fs-4 me-3"></i>
                      <div>{detailsError}</div>
                    </div>
                  ) : (
                    <div className="row g-4">
                      <div className="col-lg-5">
                        
                        {/* Editable Wi-Fi Card */}
                        <div className="card border-0 shadow-sm rounded-4 mb-4">
                          <div className="card-header bg-white border-bottom-0 pt-4 pb-0 d-flex align-items-center justify-content-between">
                            <div className="d-flex align-items-center">
                              <div className="bg-primary bg-opacity-10 text-primary p-2 rounded-3 me-3">
                                <i className="bi bi-wifi fs-5"></i>
                              </div>
                              <h6 className="mb-0 fw-bold">Wi-Fi Configuration</h6>
                            </div>
                            <span className="badge bg-success bg-opacity-10 text-success border border-success rounded-pill px-2 py-1 small">
                              {wifiData?.status || 'Enabled'}
                            </span>
                          </div>
                          
                          <div className="card-body">
                            <div className="mb-3">
                              <label className="form-label fw-semibold text-muted small">Wi-Fi SSID Name</label>
                              <div className="input-group">
                                <span className="input-group-text bg-white"><i className="bi bi-wifi text-primary"></i></span>
                                <input 
                                  type="text" 
                                  className="form-control fw-semibold text-dark" 
                                  value={editSsid}
                                  onChange={(e) => setEditSsid(e.target.value)}
                                  placeholder="Enter Wi-Fi Name"
                                />
                              </div>
                            </div>

                            <div className="mb-3">
                              <label className="form-label fw-semibold text-muted small">Wi-Fi Password</label>
                              <div className="input-group">
                                <span className="input-group-text bg-white"><i className="bi bi-key text-primary"></i></span>
                                <input 
                                  type={showWifiPassword ? "text" : "password"} 
                                  className="form-control font-monospace" 
                                  value={editPassword}
                                  onChange={(e) => setEditPassword(e.target.value)}
                                  placeholder="Enter Password"
                                />
                                <button 
                                  className="btn btn-outline-secondary" 
                                  type="button"
                                  onClick={() => setShowWifiPassword(!showWifiPassword)}
                                  title={showWifiPassword ? "Hide Password" : "Show Password"}
                                >
                                  <i className={`bi bi-eye${showWifiPassword ? '-slash' : ''}`}></i>
                                </button>
                              </div>
                            </div>

                            <button 
                              className="btn btn-primary w-100 fw-semibold rounded-3 mt-2"
                              onClick={handleSaveWifi}
                              disabled={saveWifiLoading}
                            >
                              {saveWifiLoading ? (
                                <>
                                  <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                                  Updating Router...
                                </>
                              ) : (
                                <>
                                  <i className="bi bi-check-lg me-1"></i> Save Wi-Fi Settings
                                </>
                              )}
                            </button>
                          </div>
                        </div>

                        {/* WAN Details */}
                        <div className="card border-0 shadow-sm rounded-4">
                          <div className="card-header bg-white border-bottom-0 pt-4 pb-0 d-flex align-items-center">
                            <div className="bg-info bg-opacity-10 text-info p-2 rounded-3 me-3">
                              <i className="bi bi-globe2 fs-5"></i>
                            </div>
                            <h6 className="mb-0 fw-bold">WAN / PPPoE</h6>
                          </div>
                          <div className="card-body">
                            <ul className="list-group list-group-flush">
                              <li className="list-group-item px-0 d-flex justify-content-between align-items-center border-0 pb-2">
                                <span className="text-muted">Username</span>
                                <span className="fw-semibold text-dark">{wanData?.username || 'N/A'}</span>
                              </li>
                              <li className="list-group-item px-0 d-flex justify-content-between align-items-center border-0 pb-2">
                                <span className="text-muted">Password</span>
                                <span className="fw-semibold text-dark">
                                  {wanData?.password === 'N/A' || !wanData?.password 
                                    ? <span className="badge bg-light text-muted border">Masked</span> 
                                    : wanData?.password}
                                </span>
                              </li>
                              <li className="list-group-item px-0 d-flex justify-content-between align-items-center border-0">
                                <span className="text-muted">VLAN ID</span>
                                {wanData?.vlan_id 
                                  ? <span className="badge bg-secondary rounded-pill px-3">{wanData.vlan_id}</span> 
                                  : <span className="text-muted fst-italic">Untagged</span>}
                              </li>
                            </ul>
                          </div>
                        </div>
                      </div>

                      {/* Connected Hosts */}
                      <div className="col-lg-7">
                        <div className="card border-0 shadow-sm rounded-4 h-100">
                          <div className="card-header bg-white border-bottom pt-4 pb-3 d-flex justify-content-between align-items-center">
                            <div className="d-flex align-items-center">
                              <div className="bg-success bg-opacity-10 text-success p-2 rounded-3 me-3">
                                <i className="bi bi-pc-display fs-5"></i>
                              </div>
                              <h6 className="mb-0 fw-bold">Connected Devices</h6>
                            </div>
                            <span className="badge bg-success bg-opacity-10 text-success border border-success rounded-pill px-3 py-2">
                              {hostsData?.total_connected || 0} Active
                            </span>
                          </div>
                          <div className="card-body p-0">
                            {hostsData?.hosts?.length === 0 ? (
                              <div className="text-center py-5">
                                <i className="bi bi-inbox text-muted opacity-50" style={{ fontSize: '3rem' }}></i>
                                <h6 className="text-muted mt-3">No active devices connected</h6>
                              </div>
                            ) : (
                              <div className="table-responsive">
                                <table className="table table-borderless table-hover align-middle mb-0">
                                  <thead className="table-light border-bottom">
                                    <tr>
                                      <th className="px-4 py-3 text-muted fw-semibold">Hostname</th>
                                      <th className="py-3 text-muted fw-semibold">IP Address</th>
                                      <th className="py-3 text-muted fw-semibold">MAC Address</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {hostsData?.hosts?.map((host, index) => (
                                      <tr key={index} className="border-bottom">
                                        <td className="px-4 py-3">
                                          <div className="d-flex align-items-center">
                                            <div className="bg-light p-2 rounded-circle me-3 text-secondary">
                                              <i className="bi bi-laptop"></i>
                                            </div>
                                            <span className="fw-semibold text-dark">{host.hostname || 'Unknown Device'}</span>
                                          </div>
                                        </td>
                                        <td className="py-3">
                                          <span className="badge bg-light text-dark border font-monospace px-2 py-1">
                                            {host.ip_address}
                                          </span>
                                        </td>
                                        <td className="py-3 font-monospace text-muted small">
                                          {host.mac_address}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="modal-footer bg-white border-top p-3">
                  <button type= "button" className="btn btn-light rounded-pill px-4 fw-semibold border" onClick={closeModal}>
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div className="modal-backdrop fade show" onClick={closeModal}></div>
        </>
      )}

      {/* Footer */}
      <footer className="bg-white border-top py-3 mt-auto">
        <div className="container-fluid px-4 text-center">
          <span className="text-muted small">
            ACS Manager v1 — Authorized by ZN
          </span>
        </div>
      </footer>
    </div>
  );
};

export default Dashboard;
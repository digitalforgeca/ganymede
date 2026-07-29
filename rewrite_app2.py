
app_tsx_content = """import React, { useEffect, useState, useRef } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { PiRobot, PiGear, PiFolder, PiList, PiCheckCircle, PiXCircle, PiCaretRight, PiDatabase, PiChatCircle } from 'react-icons/pi';

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const activeView = location.pathname === '/' ? 'dashboard' : location.pathname.substring(1);
  const [status, setStatus] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const [chats, setChats] = useState<any[]>([]);
  const [selectedChat, setSelectedChat] = useState<any>(null);
  const [botsList, setBotsList] = useState<any>({});

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'status') {
          setStatus(data.payload);
        } else if (data.type === 'chats') {
          setChats(data.payload || []);
        } else if (data.type === 'bots') {
          setBotsList(data.payload);
        } else if (data.chats) {
          setChats(data.chats);
        } else if (data.status) {
          setStatus(data);
        } else {
          setLogs(prev => [...prev, data]);
        }
      } catch (e) {
        setLogs(prev => [...prev, { event: event.data, level: 'info' }]);
      }
    };
    
    fetch('/api/status').then(res => res.json()).then(data => setStatus(data)).catch(err => console.error(err));
    fetch('/api/chats').then(res => res.json()).then(data => { if (data && data.chats) setChats(data.chats); }).catch(err => console.error(err));
    fetch('/api/bots').then(res => res.json()).then(data => { if (data && data.bots) setBotsList(data.bots); }).catch(err => console.error(err));

    return () => ws.close();
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <>
      <nav className="navbar has-shadow is-fixed-top" style={{ zIndex: 100, minHeight: '2.5rem', backgroundColor: 'var(--header-gold, var(--accent-gold))' }}>
        <div className="navbar-brand">
          <a role="button" className="navbar-item" id="main-sidebar-toggle" style={{ color: 'white' }}>
            <span className="icon"><PiList size={24} /></span>
          </a>
          <div className="navbar-item cinzel has-text-weight-bold is-flex is-align-items-center pl-0" style={{ color: 'white', fontSize: '1.1rem' }}>
            <img src="/ganymede-logo-light.png" alt="Ganymede Logo" style={{ maxHeight: '28px', marginRight: '10px' }} />
          </div>
        </div>
        <div className="navbar-menu is-active">
          <div className="navbar-end pr-4">
            <div className="navbar-item is-size-7" style={{ color: 'white' }}>
              <span className={`pulse ${status?.status === 'online' ? 'online' : 'offline'} mr-2`}></span>
              <span className="has-text-weight-semibold mr-4">{status?.status === 'online' ? 'Gateway Online' : 'Disconnected'}</span>
            </div>
            <div className="navbar-item is-size-7" style={{ color: 'white' }}>
              <span style={{ opacity: 0.8 }} className="mr-1">Log Level:</span> <span className="has-text-weight-bold">{status?.log_level || '--'}</span>
            </div>
            <div className="navbar-item is-size-7" style={{ color: 'white' }}>
              <span style={{ opacity: 0.8 }} className="mr-1">Data:</span> <span className="has-text-weight-bold">{status?.data_dir || '--'}</span>
            </div>
          </div>
        </div>
      </nav>

      <div className="is-flex is-fullheight" style={{ marginTop: '2.5rem', height: 'calc(100vh - 2.5rem)' }}>
        <aside className="olympus-sidebar" style={{ width: '250px', minWidth: '150px', maxWidth: '50%', overflowY: 'auto', overflowX: 'hidden', flexShrink: 0, backgroundColor: 'var(--sidebar-bg)', borderRight: '1px solid var(--border-color)' }}>
          <div className="account-badge section">
            <div className="avatar" style={{ backgroundColor: 'white', border: '2px solid var(--border-color)', overflow: 'hidden' }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="40px" height="40px">
                <path fill="#FFC107" d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12c0-6.627,5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24c0,11.045,8.955,20,20,20c11.045,0,20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"/>
                <path fill="#FF3D00" d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"/>
                <path fill="#4CAF50" d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"/>
                <path fill="#1976D2" d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571c0.001-0.001,0.002-0.001,0.003-0.002l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"/>
              </svg>
            </div>
            <div className="account-info mt-2">
              <p className="title is-5 mb-0 cinzel" style={{ fontSize: '1.1rem !important' }}>Antigravity Profile</p>
              <p className="is-size-7 has-text-grey mt-1" style={{ lineHeight: 1.2 }}>Google Account Authorized</p>
            </div>
          </div>
          
          <div className="section pt-0">
            <aside className="menu">
              <p className="menu-label">Main</p>
              <ul className="menu-list sidebar-nav mb-4">
                <li><a className={activeView === 'dashboard' ? 'is-active nav-item' : 'nav-item'} onClick={() => navigate('/')}><span className="icon is-small mr-2"><PiDatabase /></span>Dashboard</a></li>
                <li><a className={activeView === 'projects' ? 'is-active nav-item' : 'nav-item'} onClick={() => navigate('/projects')}><span className="icon is-small mr-2"><PiFolder /></span>Projects</a></li>
              </ul>
              <p className="menu-label">Configuration</p>
              <ul className="menu-list sidebar-nav">
                <li><a className={activeView === 'bots' ? 'is-active nav-item' : 'nav-item'} onClick={() => navigate('/bots')}><span className="icon is-small mr-2"><PiRobot /></span>Bots</a></li>
                <li><a className={activeView === 'settings' ? 'is-active nav-item' : 'nav-item'} onClick={() => navigate('/settings')}><span className="icon is-small mr-2"><PiGear /></span>Settings</a></li>
              </ul>
            </aside>
          </div>
        </aside>

        <div className="main-content" style={{ flex: 1, minWidth: 0, overflowY: 'auto' }}>
          <div className="view-container">
            <Routes>
              <Route path="/" element={
                <main className="section view-section pt-5">
                  <div className="columns">
                    <div className="column is-one-third">
                      <div className="box facet mb-4">
                        <h2 className="title is-5 cinzel facet-title mb-3" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>System Metrics</h2>
                        
                        <div className="is-flex is-justify-content-space-between is-align-items-center mb-3">
                          <span className="has-text-grey">Active Instances</span>
                          <span className="has-text-weight-bold is-size-5 has-text-info">{status?.metrics?.active_instances || 0}</span>
                        </div>
                        
                        <div className="mt-4 pt-3" style={{ borderTop: '1px solid #eee' }}>
                          <div className="is-flex is-justify-content-space-between mb-1">
                            <span className="is-size-7 has-text-grey">Tokens Streamed (Last Hour)</span>
                            <span className="is-size-7 has-text-weight-bold">{status?.metrics?.tokens_hour || 0} / {status?.metrics?.token_limit || 200000}</span>
                          </div>
                          <progress className="progress is-warning is-small mb-3" value={status?.metrics?.tokens_hour || 0} max={status?.metrics?.token_limit || 200000}></progress>

                          <div className="is-flex is-justify-content-space-between mb-1">
                            <span className="is-size-7 has-text-grey">API Requests vs Quota (Daily)</span>
                            <span className="is-size-7 has-text-weight-bold">{status?.metrics?.quota_used || 0} / {status?.metrics?.quota_limit || 100}</span>
                          </div>
                          <progress className="progress is-primary is-small mb-3" value={status?.metrics?.quota_used || 0} max={status?.metrics?.quota_limit || 100}></progress>
                          
                          <div className="is-flex is-justify-content-space-between mb-1">
                            <span className="is-size-7 has-text-grey">Global Model Setting</span>
                            <span className="is-size-7 has-text-weight-bold has-text-success">{status?.model || 'Default'}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="column is-two-thirds">
                      <div className="box facet h-100 is-flex is-flex-direction-column">
                        <div className="is-flex is-justify-content-space-between is-align-items-center facet-title">
                          <h2 className="title is-4 cinzel mb-0" style={{ borderBottom: 'none', paddingBottom: 0 }}>Chalice Telemetry</h2>
                          <button className="button is-small is-outlined is-info">Export JSON</button>
                        </div>
                        <div className="log-container flex-grow-1" style={{ overflowY: 'auto', flex: 1, backgroundColor: '#0a0a0a', padding: '15px', color: '#00ff00', fontFamily: 'monospace', borderRadius: '4px' }}>
                          {logs.length === 0 && <div className="log-entry system" style={{ color: '#888' }}>Waiting for agent telemetry stream...</div>}
                          {logs.map((log, i) => (
                            <div key={i} className="log-entry">
                              <span style={{ color: '#888' }}>[{new Date().toLocaleTimeString()}] </span>
                              <span style={{ color: log.level === 'error' ? '#ff4444' : '#00ff00' }}>
                                {log.event || JSON.stringify(log)} {log.payload ? `- ${JSON.stringify(log.payload)}` : ''}
                              </span>
                            </div>
                          ))}
                          <div ref={logsEndRef} />
                        </div>
                      </div>
                    </div>
                  </div>
                </main>
              } />

              <Route path="/projects" element={
                <main className="section view-section pt-5">
                  <div className="box facet">
                    <h2 className="title is-3 cinzel facet-title mb-0" style={{ border: 'none' }}>Projects</h2>
                    <p>WIP: Porting exact Project logic over.</p>
                  </div>
                </main>
              } />

              <Route path="/bots" element={
                <main className="section view-section pt-5">
                  <div className="box facet">
                    <h2 className="title is-3 cinzel facet-title">Bots</h2>
                    <p className="has-text-grey mb-4">Manage connected bot identities and their associated providers.</p>
                    <div className="columns is-multiline">
                      {Object.keys(botsList).length > 0 ? Object.entries(botsList).map(([botId, botData]: [string, any]) => (
                        <div className="column is-half" key={botId}>
                          <div className="box is-clickable" style={{ cursor: 'pointer', transition: 'all 0.2s', border: '1px solid var(--border-marble)' }} onClick={() => alert(`Opening detail for ${botData.name || botId}`)}>
                            <div className="media">
                              <div className="media-left">
                                <figure className="image is-48x48">
                                  <span className="icon is-large has-text-info"><PiRobot size={32} /></span>
                                </figure>
                              </div>
                              <div className="media-content">
                                <p className="title is-4">{botData.name || botId}</p>
                                <p className="subtitle is-6">@{botId}</p>
                              </div>
                            </div>
                            <div className="content mt-3">
                              <div className="tags">
                                <span className="tag is-info is-light">Provider: {botData.provider?.type || 'unknown'}</span>
                                <span className="tag is-primary is-light">Model: {botData.model || 'Default'}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      )) : (
                        <div className="column is-full">
                          <p className="has-text-grey">No bots configured.</p>
                        </div>
                      )}
                    </div>
                  </div>
                </main>
              } />

              <Route path="/settings" element={
                <main className="section view-section pt-5">
                  <div className="box facet">
                    <h2 className="title is-3 cinzel facet-title">Settings</h2>
                    <p>WIP: Porting exact Settings logic over.</p>
                  </div>
                </main>
              } />
            </Routes>
          </div>
        </div>
      </div>
    </>
  );
}
"""

with open('src/ganymede/web/themes/default/src/App.tsx', 'w') as f:
    f.write(app_tsx_content)

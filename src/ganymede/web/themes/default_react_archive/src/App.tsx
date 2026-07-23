import { useEffect, useState, useRef } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { PiRobot, PiGear, PiFolder, PiHouse } from 'react-icons/pi';

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const activeView = location.pathname === '/' ? 'dashboard' : location.pathname.substring(1);
  const [status, setStatus] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);
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
        } else if (data.type === 'bots') {
          setBotsList(data.payload);
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
          <div className="navbar-item cinzel has-text-weight-bold is-flex is-align-items-center" style={{ color: 'white', fontSize: '1.1rem' }}>
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
                <li><a className={activeView === 'dashboard' ? 'is-active nav-item' : 'nav-item'} onClick={() => navigate('/')}><span className="icon is-small mr-2"><PiHouse /></span>Dashboard</a></li>
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

              <Route path="/projects" element={<ProjectsView />} />

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

              <Route path="/settings" element={<SettingsView />} />
            </Routes>
          </div>
        </div>
      </div>
    </>
  );
}

function SettingsView() {
  const [activeTab, setActiveTab] = useState('global');
  const [rawConfig, setRawConfig] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [globalConfig, setGlobalConfig] = useState<any>({
    agent: {},
    bot: {}
  });

  useEffect(() => {
    fetch('/api/config')
      .then(res => res.json())
      .then(data => {
        setRawConfig(JSON.stringify(data, null, 2));
        setGlobalConfig(data);
      })
      .catch(err => console.error(err));

    fetch('/api/models')
      .then(res => res.json())
      .then(data => {
        if (data.models) setModels(data.models);
      })
      .catch(err => console.error(err));
  }, []);

  const saveGlobalConfig = () => {
    fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(globalConfig)
    })
    .then(res => {
      if (res.ok) alert('Saved successfully');
      else alert('Failed to save');
    });
  };

  const saveRawConfig = () => {
    try {
      const data = JSON.parse(rawConfig);
      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      .then(res => {
        if (res.ok) {
          alert('Saved successfully');
          setGlobalConfig(data);
        } else alert('Failed to save');
      });
    } catch(e) {
      alert("Invalid JSON format in the editor.");
    }
  };

  return (
    <main className="section view-section pt-5">
      <div className="box facet">
        <h2 className="title is-3 cinzel facet-title">Settings</h2>
        <p className="has-text-grey mb-4">Direct manipulation of Antigravity configuration files. These settings reflect exactly what is loaded from <code>~/.ganymede/config.yaml</code>.</p>
        
        <div className="tabs is-boxed is-small mb-4">
          <ul>
            <li className={activeTab === 'global' ? 'is-active' : ''} onClick={() => setActiveTab('global')}><a><span className="icon is-small"><i className="fas fa-globe"></i></span><span>Global Settings</span></a></li>
            <li className={activeTab === 'rules' ? 'is-active' : ''} onClick={() => setActiveTab('rules')}><a><span className="icon is-small"><i className="fas fa-book"></i></span><span>Rules & Workflows</span></a></li>
            <li className={activeTab === 'raw' ? 'is-active' : ''} onClick={() => setActiveTab('raw')}><a><span className="icon is-small"><i className="fas fa-code"></i></span><span>Raw Config</span></a></li>
          </ul>
        </div>

        {activeTab === 'global' && (
          <div id="settings-global-view">
            <div className="columns">
              <div className="column is-6">
                <div className="field">
                  <label className="label is-small">Global Default Model</label>
                  <div className="control">
                    <div className="select is-small is-fullwidth">
                      <select value={globalConfig?.agent?.model || ''} onChange={e => setGlobalConfig({...globalConfig, agent: {...globalConfig.agent, model: e.target.value}})}>
                        <option value="">Default (Global Config)</option>
                        {models.map(m => <option key={m} value={m}>{m}</option>)}
                      </select>
                    </div>
                  </div>
                </div>
                <div className="columns is-mobile is-vcentered mb-2 mt-2">
                  <div className="column is-6">
                    <div className="field">
                      <label className="label is-small">Execution Mode</label>
                      <div className="control">
                        <div className="select is-small is-fullwidth">
                          <select value={globalConfig?.agent?.mode || 'accept-edits'} onChange={e => setGlobalConfig({...globalConfig, agent: {...globalConfig.agent, mode: e.target.value}})}>
                            <option value="accept-edits">accept-edits</option>
                            <option value="plan">plan</option>
                          </select>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="column is-6">
                    <div className="field pt-3">
                      <label className="checkbox is-size-7 pt-2">
                        <input type="checkbox" checked={globalConfig?.agent?.skip_permissions || false} onChange={e => setGlobalConfig({...globalConfig, agent: {...globalConfig.agent, skip_permissions: e.target.checked}})} />
                        {' '}Skip Permissions (Danger)
                      </label>
                    </div>
                  </div>
                </div>
                <div className="field">
                  <label className="label is-small">Mission Statement</label>
                  <div className="control">
                    <textarea className="textarea is-small" rows={2} placeholder="assisting the user..." value={globalConfig?.agent?.mission_statement || ''} onChange={e => setGlobalConfig({...globalConfig, agent: {...globalConfig.agent, mission_statement: e.target.value}})}></textarea>
                  </div>
                </div>
                <div className="field">
                  <label className="label is-small">System Instructions Base</label>
                  <div className="control">
                    <textarea className="textarea is-small" rows={4} placeholder="Agent base instructions..." value={globalConfig?.bot?.identity || ''} onChange={e => setGlobalConfig({...globalConfig, bot: {...globalConfig.bot, identity: e.target.value}})}></textarea>
                  </div>
                </div>
                <button className="button is-small is-primary mt-2" onClick={saveGlobalConfig}>Save Global Settings</button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'raw' && (
          <div id="settings-raw-view">
            <div className="field">
              <div className="control">
                <textarea className="textarea has-background-light" rows={18} style={{ fontFamily: 'monospace', fontSize: '0.9rem' }} value={rawConfig} onChange={e => setRawConfig(e.target.value)}></textarea>
              </div>
            </div>
            <div className="field is-grouped mt-4">
              <div className="control">
                <button className="button is-primary" onClick={saveRawConfig}>Save Configuration</button>
              </div>
              <div className="control">
                <button className="button is-light" onClick={() => setRawConfig(JSON.stringify(globalConfig, null, 2))}>Discard Changes</button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'rules' && (
          <div id="settings-rules-view">
            <p className="has-text-grey mb-4">Manage Antigravity system rules (<code>~/.gemini/rules/</code>). These markdown files dictate system-wide agent instructions.</p>
            <div className="columns">
              <div className="column is-4">
                <div className="menu mb-5">
                  <p className="menu-label is-flex is-justify-content-space-between is-align-items-center">
                    <span>Active Rules</span>
                    <button className="button is-small is-success is-outlined">+ New</button>
                  </p>
                  <ul className="menu-list">
                    <li><a className="is-active">Loading rules...</a></li>
                  </ul>
                </div>
              </div>
              <div className="column is-8">
                <div className="box is-flex is-flex-direction-column" style={{ backgroundColor: '#fafafa' }}>
                  <div className="field mb-2">
                    <div className="control">
                      <input className="input cinzel has-text-weight-bold is-size-5" type="text" placeholder="rule_name.md" disabled />
                    </div>
                  </div>
                  <div className="field flex-grow-1 is-flex is-flex-direction-column">
                    <div className="control flex-grow-1 is-flex">
                      <textarea className="textarea" style={{ height: '300px', fontFamily: 'monospace' }} placeholder="Select a rule or create a new one..." disabled></textarea>
                    </div>
                  </div>
                  <div className="field is-grouped is-grouped-right mt-3">
                    <p className="control">
                      <button className="button is-danger is-outlined" disabled>Delete</button>
                    </p>
                    <p className="control">
                      <button className="button is-primary" disabled>Save Changes</button>
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

function ProjectsView() {
  const [chats, setChats] = useState<any[]>([]);
  const [chatGroups, setChatGroups] = useState<any>({});
  const [activeTab, setActiveTab] = useState<string>('');
  const [currentChatId, setCurrentChatId] = useState<string | null>(null);
  const [chatHistory, setChatHistory] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [chatInterfaceTab, setChatInterfaceTab] = useState('chat');
  const [models, setModels] = useState<string[]>([]);
  const [chatSettings, setChatSettings] = useState<any>({});
  const [chatRules, setChatRules] = useState<string>('');
  
  useEffect(() => {
    fetch('/api/chats')
      .then(res => res.json())
      .then(data => {
        if (data.chats) {
          setChats(data.chats);
          const groups: any = {};
          data.chats.forEach((chat: any) => {
            if (!groups[chat.platform]) groups[chat.platform] = [];
            groups[chat.platform].push(chat);
          });
          setChatGroups(groups);
          if (Object.keys(groups).length > 0) {
            setActiveTab(Object.keys(groups)[0]);
          }
        }
      })
      .catch(e => console.error(e));

    fetch('/api/models')
      .then(res => res.json())
      .then(data => {
        if (data.models) setModels(data.models);
      })
      .catch(err => console.error(err));
  }, []);

  const selectChat = (chatId: string) => {
    setCurrentChatId(chatId);
    setChatHistory([]);
    fetch(`/api/chats/${chatId}/history`)
      .then(res => res.json())
      .then(data => {
        if (data.messages) setChatHistory(data.messages);
      });
    fetch(`/api/chats/${chatId}/settings`)
      .then(res => res.json())
      .then(data => {
        setChatSettings(data);
        setChatRules(data.rules || '');
      });
  };

  const saveChatSettings = () => {
    if (!currentChatId) return;
    fetch(`/api/chats/${currentChatId}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(chatSettings)
    }).then(res => {
      if (res.ok) alert('Settings saved successfully');
      else alert('Failed to save settings');
    });
  };

  const activeChats = (chatGroups[activeTab] || []).filter((chat: any) => {
    const searchStr = `${chat.platform} ${chat.channel_id} ${chat.thread_id || ''} ${chat.project_name || ''}`.toLowerCase();
    return searchStr.includes(searchQuery.toLowerCase());
  });

  const currentChat = chats.find((c: any) => c.id === currentChatId);

  return (
    <main className="section view-section pt-5">
      <div className="box facet">
        <div className="is-flex is-justify-content-space-between is-align-items-center mb-4">
          <h2 className="title is-3 cinzel facet-title mb-0" style={{ border: 'none' }}>Projects</h2>
          <button className="button is-small is-outlined">
            <span>Toggle Channels</span>
          </button>
        </div>
        <div className="field">
          <div className="control has-icons-left">
            <input className="input" type="text" placeholder="Search channels by name, thread, or context..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
          </div>
        </div>
        <div className="columns mt-4 is-variable is-2">
          <div id="channels-pane" style={{ width: '330px', maxWidth: '50%', minWidth: '200px', overflowY: 'auto', overflowX: 'hidden', paddingRight: '15px', borderRight: '1px solid #eee', height: 'calc(100vh - 250px)', flexShrink: 0 }}>
            <div className="menu mb-5">
              <p className="menu-label">Channels</p>
              <div className="tabs is-small is-toggle is-fullwidth mb-3">
                <ul>
                  {Object.keys(chatGroups).map(platform => (
                    <li key={platform} className={activeTab === platform ? 'is-active' : ''} onClick={() => setActiveTab(platform)}>
                      <a><span>{platform.toUpperCase()}</span></a>
                    </li>
                  ))}
                </ul>
              </div>
              <ul className="menu-list">
                {activeChats.length > 0 ? activeChats.map((chat: any) => {
                  const displayName = chat.project_name || `${chat.platform}-${chat.channel_id}${chat.thread_id ? `-${chat.thread_id}` : ''}`;
                  return (
                    <li key={chat.id}>
                      <a className={`is-flex is-justify-content-space-between is-align-items-center ${currentChatId === chat.id ? 'is-active' : ''}`} onClick={() => selectChat(chat.id)}>
                        <div className="is-flex is-flex-direction-column" style={{ width: '100%' }}>
                          <div className="is-flex is-justify-content-space-between is-align-items-center mb-1">
                            <span>
                              <span className="icon is-small"><i className={`fas ${chat.platform === 'discord' ? 'fa-discord' : 'fa-terminal'}`}></i></span>
                              <span className="chat-name has-text-weight-semibold">{displayName}</span>
                            </span>
                            <span className="tag is-dark is-rounded" style={{ transform: 'scale(0.8)' }}>{chat.msg_count}</span>
                          </div>
                          <div className="is-size-7 has-text-grey">
                            <span className="icon is-small" style={{ fontSize: '0.6rem' }}><i className="fas fa-fingerprint"></i></span>
                            <span className="is-family-code" style={{ fontSize: '0.7rem' }}>{chat.actual_conv_id}</span>
                          </div>
                        </div>
                      </a>
                    </li>
                  );
                }) : (
                  <li><a>No active projects found.</a></li>
                )}
              </ul>
            </div>
          </div>
          
          <div className="column" id="chat-pane" style={{ flex: 1, minWidth: 0 }}>
            <div className="box is-flex is-flex-direction-column" style={{ height: 'calc(100vh - 250px)', backgroundColor: '#fafafa', overflow: 'hidden' }}>
              <div className="chat-header pb-3 mb-3 border-bottom is-flex is-justify-content-space-between is-align-items-center">
                <div>
                  <h3 className="title is-5 mb-0">{currentChat ? (currentChat.project_name || `${currentChat.platform}-${currentChat.channel_id}`) : 'Select or start a chat'}</h3>
                  <p className="subtitle is-6">{currentChat ? `Platform: ${currentChat.platform} | Channel: ${currentChat.channel_id} | AGY ID: ${currentChat.actual_conv_id}` : ''}</p>
                </div>
                <div>
                  {currentChat && (
                    <>
                      <button className="button is-small is-info is-outlined mr-2">View Artifacts</button>
                      <button className="button is-small is-info is-outlined mr-2">Export Markdown</button>
                      <button className="button is-small is-info is-outlined mr-2">Fork Chat</button>
                      <button className="button is-small is-warning is-outlined">Merge Context</button>
                    </>
                  )}
                </div>
              </div>
              
              {currentChat && (
                <div className="tabs is-small is-boxed mb-0">
                  <ul>
                    <li className={chatInterfaceTab === 'chat' ? 'is-active' : ''} onClick={() => setChatInterfaceTab('chat')}><a>Chat</a></li>
                    <li className={chatInterfaceTab === 'settings' ? 'is-active' : ''} onClick={() => setChatInterfaceTab('settings')}><a>Settings</a></li>
                    <li className={chatInterfaceTab === 'rules' ? 'is-active' : ''} onClick={() => setChatInterfaceTab('rules')}><a>Rules</a></li>
                  </ul>
                </div>
              )}

              {chatInterfaceTab === 'chat' && (
                <>
                  <div className="chat-history flex-grow-1 content" style={{ overflowY: 'auto', padding: '15px' }}>
                    {!currentChatId && <div className="has-text-centered has-text-grey mt-5">Select a project to view history.</div>}
                    {currentChatId && chatHistory.length === 0 && <div className="has-text-centered has-text-grey mt-5">Loading history...</div>}
                    {chatHistory.map((msg: any, i) => (
                      <div key={i} className={`box mb-3 ${msg.role === 'assistant' ? 'has-background-light' : 'has-background-white'}`}>
                        <div style={{ marginBottom: '8px', display: 'flex', alignItems: 'center' }}>
                          <strong>{msg.role === 'assistant' ? 'Agent' : 'You'}</strong>
                        </div>
                        <div dangerouslySetInnerHTML={{ __html: msg.content.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>') }} />
                      </div>
                    ))}
                  </div>
                  
                  {currentChatId && (
                    <div className="chat-input mt-4 pt-3 border-top" style={{ padding: '0 15px 15px' }}>
                      <div className="field has-addons">
                        <div className="control is-expanded">
                          <input className="input" type="text" placeholder="Chat natively with the executing agent..." />
                        </div>
                        <div className="control">
                          <button className="button is-info">Send</button>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}

              {chatInterfaceTab === 'settings' && (
                <div className="chat-settings" style={{ flex: 1, padding: '20px', overflowY: 'auto' }}>
                  <h4 className="title is-5 cinzel">Project Settings</h4>
                  <p className="has-text-grey mb-4">These settings are isolated to this specific project context.</p>
                  <div className="field">
                    <label className="label is-small">Project Name</label>
                    <div className="control">
                      <input className="input is-small is-fullwidth" type="text" placeholder="e.g. discord-123456" value={chatSettings.project_name || ''} onChange={e => setChatSettings({...chatSettings, project_name: e.target.value})} />
                    </div>
                  </div>
                  <div className="field">
                    <label className="label is-small">Agent Model Override</label>
                    <div className="control">
                      <div className="select is-small is-fullwidth">
                        <select value={chatSettings.model || ''} onChange={e => setChatSettings({...chatSettings, model: e.target.value})}>
                          <option value="">Default (Global Config)</option>
                          {models.map(m => <option key={m} value={m}>{m}</option>)}
                        </select>
                      </div>
                    </div>
                  </div>
                  <div className="columns is-mobile is-vcentered mb-2 mt-2">
                    <div className="column is-6">
                      <div className="field">
                        <label className="label is-small">Execution Mode Override</label>
                        <div className="control">
                          <div className="select is-small is-fullwidth">
                            <select value={chatSettings.mode || ''} onChange={e => setChatSettings({...chatSettings, mode: e.target.value})}>
                              <option value="">Default (Global Config)</option>
                              <option value="accept-edits">accept-edits</option>
                              <option value="plan">plan</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="column is-6">
                      <div className="field pt-3">
                        <label className="checkbox is-size-7 pt-2">
                          <input type="checkbox" checked={chatSettings.skip_permissions || false} onChange={e => setChatSettings({...chatSettings, skip_permissions: e.target.checked})} />
                          {' '}Skip Permissions (Danger)
                        </label>
                      </div>
                    </div>
                  </div>
                  <button className="button is-small is-primary mt-4" onClick={saveChatSettings}>Save Project Settings</button>
                </div>
              )}

              {chatInterfaceTab === 'rules' && (
                <div className="chat-rules" style={{ flex: 1, padding: '20px', overflowY: 'auto' }}>
                  <h4 className="title is-5 cinzel">Project Rules</h4>
                  <p className="has-text-grey mb-4">These rules are injected as system instructions specific to this channel.</p>
                  <div className="field">
                    <div className="control">
                      <textarea className="textarea" rows={10} placeholder="e.g. Always respond in JSON format..." value={chatRules} onChange={e => setChatRules(e.target.value)}></textarea>
                    </div>
                  </div>
                  <button className="button is-small is-primary mt-4" onClick={() => {
                    fetch(`/api/chats/${currentChatId}/settings`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({...chatSettings, rules: chatRules})
                    }).then(res => {
                      if (res.ok) alert('Rules saved successfully');
                    });
                  }}>Save Rules</button>
                </div>
              )}
              
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

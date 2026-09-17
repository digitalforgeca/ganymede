document.addEventListener("DOMContentLoaded", () => {
    // Intercept fetch to handle 401s globally
    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
        const response = await originalFetch(...args);
        const loginOverlay = document.getElementById('login-overlay');
        if (response.status === 401) {
            if (loginOverlay) {
                loginOverlay.style.setProperty('display', 'flex', 'important');
            }
        } else if (response.ok && loginOverlay) {
            loginOverlay.style.setProperty('display', 'none', 'important');
        }
        return response;
    };
    
    // DOM Elements
    const statusText = document.getElementById("status-text");
    const pulse = document.querySelector(".pulse");
    
    const valPlatform = document.getElementById("val-platform");
    const valLoglevel = document.getElementById("val-loglevel");
    const valDatadir = document.getElementById("val-datadir");
    
    const fileList = document.getElementById("file-list");
    const logContainer = document.getElementById("tab-telemetry-content") || document.getElementById("log-container");

    let ws = null;
    let currentChatHistoryData = []; // Store the messages to export later
    let botInfo = null;

    // Format bytes to human readable
    function formatBytes(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    // Antigravity formatting: GitHub-style alerts and tool accordions
    function formatAgentMarkdown(content) {
        if (!content) return "";
        let text = content;

        // 1. Process GitHub/Antigravity style alerts: > [!NOTE], > [!TIP], etc.
        text = text.replace(/^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*\n((?:^>.*$\n?)*)/gim, (match, alertType, bodyLines) => {
            const typeLower = alertType.toLowerCase();
            const cleanBody = bodyLines.replace(/^>[ \t]?/gm, '').trim();
            const iconMap = {
                note: 'ph-info',
                tip: 'ph-lightbulb',
                important: 'ph-warning-circle',
                warning: 'ph-warning',
                caution: 'ph-shield-warning'
            };
            const icon = iconMap[typeLower] || 'ph-info';
            const title = alertType.charAt(0).toUpperCase() + alertType.slice(1).toLowerCase();
            return `\n<div class="antigravity-alert antigravity-alert-${typeLower}"><div class="antigravity-alert-header"><i class="ph ${icon}"></i> ${title}</div><div class="antigravity-alert-body">${cleanBody}</div></div>\n`;
        });

        // 2. Parse tool execution lines into interactive accordion cards
        text = text.replace(/`?(?:Calling tool|Tool:|Executing tool)\s+([a-zA-Z0-9_\-]+)`?[\s\S]*?(?=\n\n|$)/gi, (match, toolName) => {
            const cleanMatch = match.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return `\n<details class="tool-call-card"><summary class="tool-call-summary"><span class="tag is-info is-light mr-2">Tool Call</span><strong>${toolName}</strong></summary><pre><code>${cleanMatch}</code></pre></details>\n`;
        });

        // 3. Render markdown via marked
        if (window.marked) {
            return marked.parse(text);
        } else {
            return text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
        }
    }
    
    function getAgentHeaderHtml() {
        if (botInfo) {
            const avatarHtml = botInfo.avatar_url ? `<img src="${botInfo.avatar_url}" referrerpolicy="no-referrer" style="width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px;">` : '';
            return `<div style="margin-bottom: 8px; display: flex; align-items: center;">
                        ${avatarHtml}
                        <strong>${botInfo.name}</strong>
                        <span class="has-text-grey ml-2 is-size-7" style="font-family: monospace;">(${botInfo.id})</span>
                    </div>`;
        }
        return `<strong>Agent:</strong><br>`;
    }
    
    let userInfo = null;

    function getUserHeaderHtml() {
        if (userInfo) {
            const avatarHtml = userInfo.avatar_url ? `<img src="${userInfo.avatar_url}" referrerpolicy="no-referrer" style="width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px;">` : `<svg style="width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px; background: var(--bg-surface-alt); fill: var(--text-muted); padding: 4px; border: 1px solid var(--border-subtle);" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>`;
            return `<div style="margin-bottom: 8px; display: flex; align-items: center;">
                        ${avatarHtml}
                        <strong>${userInfo.name}</strong>
                    </div>`;
        }
        const defaultUserIcon = `<svg style="width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px; background: var(--bg-surface-alt); fill: var(--text-muted); padding: 4px; border: 1px solid var(--border-subtle);" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>`;
        return `<div style="margin-bottom: 8px; display: flex; align-items: center;">
                    ${defaultUserIcon}
                    <strong>You</strong>
                </div>`;
    }

    // 1. Fetch Configuration API
    async function fetchStatus() {
        try {
            const res = await fetch('/api/status');
            if (!res.ok) throw new Error("Status API failed");
            const data = await res.json();
            
            if (valPlatform) valPlatform.textContent = data.platform || "Unknown";
            if (valLoglevel) valLoglevel.textContent = data.log_level || "Unknown";
            if (valDatadir) valDatadir.textContent = data.data_dir || "Unknown";
            
            const modelText = document.getElementById('metric-model-text');
            if (modelText) modelText.textContent = data.model || "Default";
            
            if (data.metrics) {
                const activeEl = document.getElementById('metric-active-instances');
                if (activeEl) activeEl.textContent = data.metrics.active_instances || 0;
                
                const tokenText = document.getElementById('metric-tokens-text');
                const tokenBar = document.getElementById('metric-tokens-bar');
                if (tokenText && tokenBar) {
                    const tokenUsed = data.metrics.tokens_hour || 0;
                    const tokenLimit = data.metrics.token_limit || 200000;
                    tokenText.textContent = `${tokenUsed.toLocaleString()} / ${tokenLimit.toLocaleString()}`;
                    const tokenPct = (tokenUsed / Math.max(1, tokenLimit)) * 100;
                    tokenBar.value = tokenPct;
                }
                
                const quotaText = document.getElementById('metric-quota-text');
                const quotaBar = document.getElementById('metric-quota-bar');
                if (quotaText && quotaBar) {
                    quotaText.textContent = `${data.metrics.quota_used} / ${data.metrics.quota_limit}`;
                    const pct = (data.metrics.quota_used / Math.max(1, data.metrics.quota_limit)) * 100;
                    quotaBar.value = pct;
                }
                
                const sidebarTokens = document.getElementById('sidebar-tokens-left');
                if (sidebarTokens) {
                    const tokensRemaining = Math.max(0, data.metrics.token_limit - data.metrics.tokens_hour);
                    sidebarTokens.textContent = tokensRemaining.toLocaleString();
                }
            }
            
            if (data.bot_info) {
                botInfo = data.bot_info;
                
                const cardAvatar = document.getElementById('bot-card-avatar');
                const cardName = document.getElementById('bot-card-name');
                const cardId = document.getElementById('bot-card-id');
                const cardPlatform = document.getElementById('bot-card-platform');
                
                if (cardName) {
                    cardName.textContent = botInfo.name || "Unknown Bot";
                    if (botInfo.avatar_url && cardAvatar) {
                        cardAvatar.src = botInfo.avatar_url;
                    }
                    if (cardId) {
                        cardId.textContent = botInfo.id || "--";
                    }
                    if (cardPlatform) {
                        cardPlatform.textContent = data.platform || "--";
                    }
                }
            }
            
            setOnline(data.status === "online");
        } catch (e) {
            console.error("Failed to fetch status", e);
            setOnline(false);
        }
    }

    // 2. Fetch Chat Files API
    async function fetchChatFiles(chatId) {
        if (!chatId) return;
        
        try {
            const res = await fetch(`/api/chats/${chatId}/files`);
            if (!res.ok) throw new Error("Files API failed");
            const data = await res.json();
            
            document.getElementById('artifacts-subtitle').textContent = `Brain Directory: ${data.workspace || "Unknown"}`;
            
            fileList.innerHTML = '';
            if (data.files && data.files.length > 0) {
                data.files.forEach(f => {
                    const li = document.createElement('li');
                    li.className = 'is-flex is-justify-content-space-between mb-1';
                    li.innerHTML = `<span class="file-name has-text-info" style="word-break: break-all; margin-right: 10px;">${f.name}</span><span class="file-size has-text-grey">${formatBytes(f.size)}</span>`;
                    fileList.appendChild(li);
                });
            } else {
                fileList.innerHTML = '<li class="empty-state has-text-grey">No artifacts found.</li>';
            }
        } catch (e) {
            console.error("Failed to fetch files", e);
            fileList.innerHTML = '<li class="empty-state has-text-danger">Error loading artifacts.</li>';
        }
    }

    // 3. Connect to Telemetry WebSocket API
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;
        
        ws = new WebSocket(wsUrl);
        
        ws.onopen = () => {
            appendLog('Connected to Ganymede Telemetry Stream.', 'system');
            // Do not force setOnline(true) here; let /api/status dictate it
        };
        
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                
                // Determine style based on event content
                let style = 'event';
                if (data.level === 'error' || data.error) style = 'error';
                else if (data.toolAction || data.action) style = 'action';
                
                let message = data.event || JSON.stringify(data);
                if (data.payload) message += ` - ${JSON.stringify(data.payload)}`;
                
                appendLog(message, style);
                // Track active subagents & tasks for Antigravity-style visualization
                if (data.event === "PreToolUse") {
                    const payload = data.payload || {};
                    const convId = payload.conversationId || data.ganymede_conv_id || "agent-main";
                    const toolCall = payload.toolCall || {};
                    const args = toolCall.args || {};
                    activeSubagents.set(convId, {
                        role: args.toolSummary || toolCall.name || "Worker Agent",
                        status: "running",
                        model: "Gemini 3.7 Flash",
                        lastTool: toolCall.name || "Tool",
                        actionSummary: args.toolAction || args.CommandLine || JSON.stringify(args).slice(0, 100)
                    });
                    updateSubagentUI();
                } else if (data.event === "Stop") {
                    const convId = data.payload?.conversationId || data.ganymede_conv_id;
                    if (convId && activeSubagents.has(convId)) {
                        const existing = activeSubagents.get(convId);
                        existing.status = "idle";
                        existing.lastTool = "Completed";
                        activeSubagents.set(convId, existing);
                        updateSubagentUI();
                    }
                }
                
                // Handle streaming to active chat
                if (data.context && data.context === currentChatId) {
                    if (data.event === "Agent Stream Start") {
                        const msgDiv = document.createElement('div');
                        msgDiv.className = 'box chat-bubble-agent mb-3';
                        msgDiv.id = data.payload.msg_id;
                        let safeContent = data.payload.content || "⏳ *Thinking...*";
                        safeContent = formatAgentMarkdown(safeContent);
                        msgDiv.innerHTML = `${getAgentHeaderHtml()}${safeContent}`;
                        
                        if (document.getElementById('chat-history').querySelector('.has-text-grey')) {
                            document.getElementById('chat-history').innerHTML = ''; // clear empty state
                        }
                        document.getElementById('chat-history').appendChild(msgDiv);
                        document.getElementById('chat-history').scrollTop = document.getElementById('chat-history').scrollHeight;
                    } else if (data.event === "Agent Stream Edit") {
                        const msgDiv = document.getElementById(data.payload.msg_id);
                        if (msgDiv) {
                            let safeContent = data.payload.content;
                            safeContent = formatAgentMarkdown(safeContent);
                            msgDiv.innerHTML = `${getAgentHeaderHtml()}${safeContent}`;
                            document.getElementById('chat-history').scrollTop = document.getElementById('chat-history').scrollHeight;
                        }
                    } else if (data.event === "Agent Stream End" || data.event === "Agent Response") {
                        // Reload full chat history to get the finalized database entry and correct markdown
                        setTimeout(() => loadChatHistory(currentChatId), 500);
                    }
                }
            } catch (e) {
                appendLog(event.data, 'event');
            }
        };
        
        ws.onclose = () => {
            appendLog('Connection to telemetry stream lost. Reconnecting in 5s...', 'error');
            setTimeout(connectWebSocket, 5000);
        };
        
        ws.onerror = () => {
            ws.close();
        };
    }

    function appendLog(message, type = 'system') {
        const container = document.getElementById("tab-telemetry-content") || logContainer;
        if (!container) return;

        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        
        const time = new Date().toLocaleTimeString();
        entry.innerHTML = `<span class="log-time">[${time}]</span><span class="log-msg">${message}</span>`;
        
        container.appendChild(entry);
        
        // Auto scroll to bottom
        if (container.children.length > 200) {
            container.removeChild(container.firstChild); // Keep memory bounded
        }
        container.scrollTop = container.scrollHeight;
    }

    function setOnline(isOnline) {
        if (isOnline) {
            pulse.classList.remove('offline');
            pulse.classList.add('online');
            statusText.textContent = 'Gateway Online';
        } else {
            pulse.classList.remove('online');
            pulse.classList.add('offline');
            statusText.textContent = 'Gateway Offline';
        }
    }

    // 4. UI Routing logic
    function setupRouting() {
        const navItems = document.querySelectorAll('.sidebar-nav .nav-item');
        const views = document.querySelectorAll('.view-section');

        function handleRoute(explicitHash) {
            let hash = (typeof explicitHash === 'string' && explicitHash) ? explicitHash : window.location.hash;
            if (!hash) {
                hash = '#view-dashboard';
            }
            
            // Extract the base view id (e.g., #view-bots?botId=xxx -> view-bots)
            let targetId = hash.substring(1).split('?')[0];
            if (!document.getElementById(targetId)) {
                targetId = 'view-dashboard';
            }

            console.log("[Router] handleRoute targetId:", targetId, "hash:", hash);
            
            // Remove active class from all nav items
            navItems.forEach(nav => nav.classList.remove('is-active'));
            
            // Add active class to clicked item (match by data-target)
            let navTarget = targetId;
            if (targetId === 'view-agent-detail') navTarget = 'view-agents';
            const activeNav = document.querySelector(`.sidebar-nav .nav-item[data-target="${navTarget}"]`);
            if (activeNav) activeNav.classList.add('is-active');
            
            // Hide all views
            views.forEach(view => {
                view.classList.add('is-hidden');
            });
            
            // Show target view
            const targetView = document.getElementById(targetId);
            if (targetView) {
                targetView.classList.remove('is-hidden');
                console.log("[Router] Activated view element:", targetId);
            } else {
                console.error("[Router] Target view element not found:", targetId);
            }
            
            // Trigger specific actions based on the view
            try {
                if (targetId === 'view-agents' || targetId === 'view-bots') {
                    if (typeof loadAgents === 'function') loadAgents();
                } else if (targetId === 'view-agent-detail' || targetId === 'view-bot-detail') {
                    const params = new URLSearchParams(hash.split('?')[1] || '');
                    const agentId = params.get('id') || 'default';
                    if (typeof loadAgentDetails === 'function') loadAgentDetails(agentId);
                } else if (targetId === 'view-channels') {
                    if (typeof loadChannels === 'function') loadChannels();
                } else if (targetId === 'view-chats') {
                    const params = new URLSearchParams(hash.split('?')[1] || '');
                    if (params.has('chat') && window.selectChatById) {
                        window.selectChatById(params.get('chat'));
                    } else if (window.selectFirstChat) {
                        window.selectFirstChat();
                    }
                    if (params.has('tab') && window.selectChatTab) {
                        window.selectChatTab(params.get('tab'));
                    } else if (window.selectChatTab) {
                        window.selectChatTab('chat');
                    }
                } else if (targetId === 'view-settings') {
                    if (window.loadConfig) window.loadConfig();
                    const params = new URLSearchParams(hash.split('?')[1] || '');
                    if (params.has('tab') && window.selectSettingsTab) {
                        window.selectSettingsTab(params.get('tab'));
                    } else if (window.selectSettingsTab) {
                        window.selectSettingsTab('global');
                    }
                }
            } catch (err) {
                console.error("Error during route handling:", err);
            }
        }

        window.handleRoute = handleRoute;
        window.addEventListener('hashchange', () => handleRoute());
        
        console.log("[Router] Initializing navItems click listeners, count:", navItems.length);
        navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const target = item.getAttribute('data-target') || item.getAttribute('href');
                console.log("[Router] Nav item clicked:", target);
                let targetHash = target;
                if (!targetHash.startsWith('#')) {
                    targetHash = '#' + targetHash;
                }
                if (window.location.hash !== targetHash) {
                    window.location.hash = targetHash;
                }
                handleRoute(targetHash);
            });
        });
        
        // Initial route handling
        handleRoute();
    }

    function setupPanes() {
        // 1. Channels Pane (Projects View)
        const toggleChannelsBtn = document.getElementById('btn-toggle-channels');
        const toggleChannelsText = document.getElementById('btn-toggle-channels-text');
        const channelsPane = document.getElementById('channels-pane');
        const handleChannels = document.getElementById('handle-channels');
        
        // Restore saved channels pane width & state
        const savedChannelsWidth = localStorage.getItem('ganymede_channels_width');
        if (savedChannelsWidth && channelsPane) {
            channelsPane.style.width = `${savedChannelsWidth}px`;
        }
        const savedChannelsCollapsed = localStorage.getItem('ganymede_channels_collapsed') === 'true';
        if (savedChannelsCollapsed && channelsPane) {
            channelsPane.classList.add('is-hidden');
            if (toggleChannelsText) toggleChannelsText.textContent = 'Show Channels';
            if (toggleChannelsBtn) {
                toggleChannelsBtn.setAttribute('data-tooltip', 'Show Channels (Cmd+E)');
                toggleChannelsBtn.classList.add('is-active-toggle');
            }
        }

        if (toggleChannelsBtn && channelsPane) {
            toggleChannelsBtn.addEventListener('click', () => {
                channelsPane.classList.toggle('is-hidden');
                const isHidden = channelsPane.classList.contains('is-hidden');
                if (toggleChannelsText) {
                    toggleChannelsText.textContent = isHidden ? 'Show Channels' : 'Hide Channels';
                }
                toggleChannelsBtn.setAttribute('data-tooltip', isHidden ? 'Show Channels (Cmd+E)' : 'Hide Channels (Cmd+E)');
                toggleChannelsBtn.classList.toggle('is-active-toggle', isHidden);
                localStorage.setItem('ganymede_channels_collapsed', isHidden);
            });
        }
        
        // 2. Main Sidebar Navigation
        const mainToggleBtn = document.getElementById('main-sidebar-toggle');
        const olympusSidebar = document.querySelector('.olympus-sidebar');
        const mainContent = document.querySelector('.main-content');
        const handleMain = document.getElementById('handle-main');
        
        // Restore saved sidebar width & state
        const savedSidebarWidth = localStorage.getItem('ganymede_sidebar_width');
        if (savedSidebarWidth && olympusSidebar) {
            olympusSidebar.style.width = `${savedSidebarWidth}px`;
        }
        const savedSidebarCollapsed = localStorage.getItem('ganymede_sidebar_collapsed') === 'true';
        if (savedSidebarCollapsed && olympusSidebar) {
            olympusSidebar.classList.add('is-hidden');
            if (mainToggleBtn) mainToggleBtn.classList.add('is-active-toggle');
        }

        if (mainToggleBtn && olympusSidebar && mainContent) {
            mainToggleBtn.addEventListener('click', () => {
                olympusSidebar.classList.toggle('is-hidden');
                const isHidden = olympusSidebar.classList.contains('is-hidden');
                mainToggleBtn.classList.toggle('is-active-toggle', isHidden);
                localStorage.setItem('ganymede_sidebar_collapsed', isHidden);
            });
        }

        // 3. Dashboard Metrics Pane
        const btnToggleMetrics = document.getElementById('btn-toggle-metrics');
        const btnExpandMetrics = document.getElementById('btn-expand-metrics');
        const metricsPane = document.getElementById('dashboard-metrics-pane');
        const telemetryPane = document.getElementById('dashboard-telemetry-pane');

        function setMetricsCollapsed(collapsed) {
            if (!metricsPane || !telemetryPane) return;
            if (collapsed) {
                metricsPane.classList.add('is-hidden');
                telemetryPane.classList.remove('is-two-thirds');
                telemetryPane.classList.add('is-full');
                if (btnExpandMetrics) btnExpandMetrics.classList.remove('is-hidden');
            } else {
                metricsPane.classList.remove('is-hidden');
                telemetryPane.classList.remove('is-full');
                telemetryPane.classList.add('is-two-thirds');
                if (btnExpandMetrics) btnExpandMetrics.classList.add('is-hidden');
            }
            localStorage.setItem('ganymede_metrics_collapsed', collapsed ? 'true' : 'false');
        }

        if (btnToggleMetrics) {
            btnToggleMetrics.addEventListener('click', () => setMetricsCollapsed(true));
        }
        if (btnExpandMetrics) {
            btnExpandMetrics.addEventListener('click', () => setMetricsCollapsed(false));
        }

        // Restore saved metrics collapsed state
        if (localStorage.getItem('ganymede_metrics_collapsed') === 'true') {
            setMetricsCollapsed(true);
        }
        
        // 4. Resizable Split Panes
        function makeResizable(pane, handle, storageKey) {
            if (!pane || !handle) return;
            let isResizing = false;
            let startX = 0;
            let startWidth = 0;
            
            handle.addEventListener('mousedown', (e) => {
                isResizing = true;
                startX = e.clientX;
                startWidth = pane.offsetWidth;
                handle.classList.add('is-dragging');
                document.body.style.cursor = 'col-resize';
                e.preventDefault();
            });
            
            document.addEventListener('mousemove', (e) => {
                if (!isResizing) return;
                const newWidth = Math.max(160, startWidth + (e.clientX - startX));
                pane.style.width = `${newWidth}px`;
            });
            
            document.addEventListener('mouseup', () => {
                if (isResizing) {
                    isResizing = false;
                    handle.classList.remove('is-dragging');
                    document.body.style.cursor = '';
                    if (storageKey) {
                        localStorage.setItem(storageKey, pane.offsetWidth);
                    }
                }
            });
        }
        
        makeResizable(channelsPane, handleChannels, 'ganymede_channels_width');
        makeResizable(olympusSidebar, handleMain, 'ganymede_sidebar_width');

        // 5. Global Keyboard Shortcuts
        document.addEventListener('keydown', (e) => {
            // Cmd+B / Ctrl+B: Toggle Sidebar
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b' && !e.shiftKey) {
                e.preventDefault();
                if (mainToggleBtn) mainToggleBtn.click();
            }
            // Cmd+E / Ctrl+E: Toggle Channels Pane in Projects view
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'e' && !e.shiftKey) {
                const viewChats = document.getElementById('view-chats');
                if (viewChats && !viewChats.classList.contains('is-hidden') && toggleChannelsBtn) {
                    e.preventDefault();
                    toggleChannelsBtn.click();
                }
            }
            // Escape: Close modals
            if (e.key === 'Escape') {
                const activeModals = document.querySelectorAll('.modal.is-active');
                activeModals.forEach(m => m.classList.remove('is-active'));
            }
        });
    }
    
    window.selectChatTab = function(target) {
        if (!target) target = 'chat';
        const tabList = document.querySelectorAll('#chat-tabs-container li');
        const viewChat = document.getElementById('chat-history');
        const viewSettings = document.getElementById('chat-settings-view');
        const viewRules = document.getElementById('chat-rules-view');
        const viewInput = document.getElementById('chat-input-area');
        
        tabList.forEach(t => t.classList.remove('is-active'));
        const activeTab = document.querySelector(`#chat-tabs-container li[data-tab="${target}"]`);
        if (activeTab) activeTab.classList.add('is-active');
        
        viewChat.classList.add('is-hidden');
        viewInput.classList.add('is-hidden');
        viewSettings.classList.add('is-hidden');
        viewRules.classList.add('is-hidden');
        
        if (target === 'chat') {
            viewChat.classList.remove('is-hidden');
            viewInput.classList.remove('is-hidden');
        } else if (target === 'settings') {
            viewSettings.classList.remove('is-hidden');
        } else if (target === 'rules') {
            viewRules.classList.remove('is-hidden');
        }
    };

    function setupChatTabs() {
        const tabList = document.querySelectorAll('#chat-tabs-container li');
        tabList.forEach(tab => {
            tab.addEventListener('click', (e) => {
                e.preventDefault();
                const target = tab.dataset.tab;
                const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
                params.set('tab', target);
                window.location.hash = `#view-chats?${params.toString()}`;
                if (window.selectChatTab) window.selectChatTab(target);
            });
        });
    }

    window.selectSettingsTab = function(target) {
        if (!target) target = 'global';
        const tabList = document.querySelectorAll('#settings-tabs-container li');
        const viewGlobal = document.getElementById('settings-global-view');
        const viewRules = document.getElementById('settings-rules-view');
        const viewRaw = document.getElementById('settings-raw-view');
        
        tabList.forEach(t => t.classList.remove('is-active'));
        const activeTab = document.querySelector(`#settings-tabs-container li[data-tab="${target}"]`);
        if (activeTab) activeTab.classList.add('is-active');
        
        viewGlobal?.classList.add('is-hidden');
        viewRules?.classList.add('is-hidden');
        viewRaw?.classList.add('is-hidden');
        
        if (target === 'global') {
            viewGlobal?.classList.remove('is-hidden');
        } else if (target === 'rules') {
            viewRules?.classList.remove('is-hidden');
            if (window.loadRules) window.loadRules();
        } else if (target === 'raw') {
            viewRaw?.classList.remove('is-hidden');
        }
    };

    function setupSettingsTabs() {
        const tabList = document.querySelectorAll('#settings-tabs-container li');
        tabList.forEach(tab => {
            tab.addEventListener('click', (e) => {
                e.preventDefault();
                const target = tab.dataset.tab;
                window.location.hash = `#view-settings?tab=${target}`;
                if (window.selectSettingsTab) window.selectSettingsTab(target);
            });
        });
    }

    // 5. Native Web Chat Invocation
    let currentChatId = null;
    let chatGroups = {};
    let activeChatTab = null;

    function applyChatSearch() {
        const query = document.getElementById('project-search').value.toLowerCase();
        if (!activeChatTab || !chatGroups[activeChatTab]) return;
        
        let filtered = chatGroups[activeChatTab];
        if (query) {
            filtered = filtered.filter(chat => {
                const searchStr = `${chat.platform} ${chat.channel_id} ${chat.thread_id || ''} ${chat.project_name || ''}`.toLowerCase();
                return searchStr.includes(query);
            });
        }
        renderChats(filtered);
    }
    
    document.getElementById('project-search').addEventListener('input', applyChatSearch);
    
    window.selectChatById = function(chatId) {
        if (!chatId) return;
        
        let targetChat = null;
        for (const platform in chatGroups) {
            const found = chatGroups[platform].find(c => c.id === chatId);
            if (found) {
                targetChat = found;
                break;
            }
        }
        
        if (!targetChat) return;
        
        document.querySelectorAll('#chat-list a').forEach(el => {
            if (el.getAttribute('href') === `#view-chats?chat=${chatId}`) {
                el.classList.add('is-active');
            } else {
                el.classList.remove('is-active');
            }
        });
        
        const displayName = targetChat.project_name || `${targetChat.platform}-${targetChat.channel_id}${targetChat.thread_id ? `-${targetChat.thread_id}` : ''}`;
        currentChatId = targetChat.id;
        document.getElementById('chat-title').textContent = displayName;
        document.getElementById('chat-subtitle').textContent = `Platform: ${targetChat.platform} | Channel: ${targetChat.channel_id} | AGY ID: ${targetChat.actual_conv_id}`;
        document.getElementById('btn-export-chat').classList.remove('is-hidden');
        document.getElementById('btn-fork-chat').classList.remove('is-hidden');
        document.getElementById('btn-view-artifacts').classList.remove('is-hidden');
        document.getElementById('btn-merge-context').classList.remove('is-hidden');
        const chatTabs = document.getElementById('chat-tabs-container');
        if (chatTabs) chatTabs.classList.remove('is-hidden');
        loadChatHistory(targetChat.id);
        fetchChatFiles(targetChat.id);
        fetchChatSettings(targetChat.id);
    };

    function renderChats(chatsToRender) {
        const chatList = document.getElementById('chat-list');
        chatList.innerHTML = '';
        chatsToRender.forEach(chat => {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.className = "is-flex is-justify-content-space-between is-align-items-center";
            a.href = `#view-chats?chat=${chat.id}`;
            const displayName = chat.project_name || `${chat.platform}-${chat.channel_id}${chat.thread_id ? `-${chat.thread_id}` : ''}`;
            a.innerHTML = `
                <div class="is-flex is-flex-direction-column" style="width: 100%;">
                    <div class="is-flex is-justify-content-space-between is-align-items-center mb-1">
                        <span>
                            <span class="icon is-small"><i class="fas ${chat.platform === 'discord' ? 'fa-discord' : 'fa-terminal'}"></i></span>
                            <span class="chat-name has-text-weight-semibold">${displayName}</span>
                        </span>
                        <span class="tag is-dark is-rounded" style="transform: scale(0.8);">${chat.msg_count}</span>
                    </div>
                    <div class="is-size-7 has-text-grey">
                        <span class="icon is-small" style="font-size: 0.6rem;"><i class="ph ph-fingerprint"></i></span>
                        <span class="is-family-code" style="font-size: 0.7rem;">${chat.actual_conv_id}</span>
                    </div>
                </div>
            `;
            
            if (currentChatId === chat.id) {
                a.classList.add('is-active');
            }
            
            a.addEventListener('click', (e) => {
                e.preventDefault();
                window.location.hash = `#view-chats?chat=${chat.id}`;
                if (window.selectChatById) {
                    window.selectChatById(chat.id);
                }
            });
            
            li.appendChild(a);
            chatList.appendChild(li);
        });
    }

    window.selectFirstChat = function() {
        if (!currentChatId && chatGroups) {
            for (const platform in chatGroups) {
                if (chatGroups[platform] && chatGroups[platform].length > 0) {
                    window.selectChatById(chatGroups[platform][0].id);
                    break;
                }
            }
        }
    };

    async function fetchChats() {
        try {
            const res = await fetch('/api/chats');
            if (!res.ok) throw new Error("Failed to load chats");
            const data = await res.json();
            
            const chatList = document.getElementById('chat-list');
            if (data.chats && data.chats.length > 0) {
                // Group by platform
                chatGroups = {};
                data.chats.forEach(chat => {
                    if (!chatGroups[chat.platform]) chatGroups[chat.platform] = [];
                    chatGroups[chat.platform].push(chat);
                });
                
                // Build tabs
                const tabsList = document.getElementById('project-tabs');
                if (tabsList) {
                    activeChatTab = document.querySelector('#project-tabs li.is-active')?.dataset?.platform;
                    if (!activeChatTab || !chatGroups[activeChatTab]) {
                        activeChatTab = Object.keys(chatGroups)[0];
                    }
                    
                    tabsList.innerHTML = '';
                    Object.keys(chatGroups).forEach(platform => {
                        const li = document.createElement('li');
                        li.dataset.platform = platform;
                        if (platform === activeChatTab) li.classList.add('is-active');
                        li.innerHTML = `<a><span>${platform.toUpperCase()}</span></a>`;
                        li.addEventListener('click', () => {
                            document.querySelectorAll('#project-tabs li').forEach(el => el.classList.remove('is-active'));
                            li.classList.add('is-active');
                            activeChatTab = platform;
                            applyChatSearch();
                        });
                        tabsList.appendChild(li);
                    });
                    
                    applyChatSearch();
                } else {
                    renderChats(data.chats);
                }

                if (window.location.hash.startsWith('#view-chats') && !currentChatId) {
                    const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
                    if (params.has('chat') && window.selectChatById) {
                        window.selectChatById(params.get('chat'));
                    } else if (window.selectFirstChat) {
                        window.selectFirstChat();
                    }
                }
            } else {
                document.getElementById('chat-list').innerHTML = '<li><a>No active projects found.</a></li>';
            }
        } catch (e) {
            console.error(e);
            document.getElementById('chat-list').innerHTML = '<li><a>Error loading projects</a></li>';
        }
    }
    
    let currentChatPagination = {
        chatId: null,
        offset: 0,
        limit: 40,
        hasMore: false,
        isLoading: false
    };

    function renderMessageDiv(msg) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `box mb-3 ${msg.role === 'assistant' ? 'chat-bubble-agent' : 'chat-bubble-user'}`;
        const safeContent = formatAgentMarkdown(msg.content);
        const roleLabel = msg.role === 'assistant' ? getAgentHeaderHtml() : getUserHeaderHtml();
        msgDiv.innerHTML = `${roleLabel}${safeContent}`;
        return msgDiv;
    }

    async function loadChatHistory(chatId) {
        const chatHistory = document.getElementById('chat-history');
        chatHistory.innerHTML = '<div class="has-text-centered has-text-muted mt-5"><i class="ph ph-spinner ph-spin mr-1"></i> Loading conversation...</div>';
        
        currentChatPagination = {
            chatId: chatId,
            offset: 0,
            limit: 40,
            hasMore: false,
            isLoading: true
        };

        try {
            const res = await fetch(`/api/chats/${chatId}/history?limit=${currentChatPagination.limit}&offset=0`);
            if (!res.ok) throw new Error("Failed to load chat history");
            const data = await res.json();
            
            currentChatHistoryData = data.messages || [];
            currentChatPagination.hasMore = !!data.has_more;
            currentChatPagination.offset = 0;
            currentChatPagination.isLoading = false;
            
            chatHistory.innerHTML = '';
            
            if (currentChatPagination.hasMore) {
                const loadMoreContainer = document.createElement('div');
                loadMoreContainer.id = 'chat-load-more-container';
                loadMoreContainer.className = 'has-text-centered my-2';
                loadMoreContainer.innerHTML = `
                    <button class="button is-small is-ghost" id="btn-load-more-history" data-tooltip="Load earlier conversation" data-tooltip-pos="bottom">
                        <i class="ph ph-arrow-counter-clockwise mr-1"></i> Load Earlier Messages
                    </button>
                `;
                chatHistory.appendChild(loadMoreContainer);
                loadMoreContainer.querySelector('#btn-load-more-history').addEventListener('click', loadEarlierMessages);
            }

            if (currentChatHistoryData.length > 0) {
                const fragment = document.createDocumentFragment();
                currentChatHistoryData.forEach(msg => {
                    fragment.appendChild(renderMessageDiv(msg));
                });
                chatHistory.appendChild(fragment);
            } else {
                chatHistory.innerHTML = '<div class="has-text-centered has-text-muted mt-5">No history yet. Say hello!</div>';
            }
            chatHistory.scrollTop = chatHistory.scrollHeight;
        } catch (e) {
            console.error(e);
            currentChatPagination.isLoading = false;
            chatHistory.innerHTML = `<div class="has-text-centered has-text-danger mt-5">Error: ${e.message}</div>`;
        }
    }

    async function loadEarlierMessages() {
        if (!currentChatPagination.hasMore || currentChatPagination.isLoading || !currentChatPagination.chatId) return;
        
        currentChatPagination.isLoading = true;
        const loadMoreBtn = document.getElementById('btn-load-more-history');
        if (loadMoreBtn) {
            loadMoreBtn.innerHTML = '<i class="ph ph-spinner ph-spin mr-1"></i> Loading earlier messages...';
            loadMoreBtn.disabled = true;
        }

        const nextOffset = currentChatPagination.offset + currentChatPagination.limit;
        const chatHistory = document.getElementById('chat-history');
        const prevScrollHeight = chatHistory.scrollHeight;
        const prevScrollTop = chatHistory.scrollTop;

        try {
            const res = await fetch(`/api/chats/${currentChatPagination.chatId}/history?limit=${currentChatPagination.limit}&offset=${nextOffset}`);
            if (!res.ok) throw new Error("Failed to load earlier messages");
            const data = await res.json();
            
            const olderMessages = data.messages || [];
            currentChatPagination.offset = nextOffset;
            currentChatPagination.hasMore = !!data.has_more;
            
            // Prepend to currentChatHistoryData for export
            currentChatHistoryData = [...olderMessages, ...currentChatHistoryData];

            const loadMoreContainer = document.getElementById('chat-load-more-container');
            if (loadMoreContainer) {
                if (!currentChatPagination.hasMore) {
                    loadMoreContainer.remove();
                } else if (loadMoreBtn) {
                    loadMoreBtn.innerHTML = '<i class="ph ph-arrow-counter-clockwise mr-1"></i> Load Earlier Messages';
                    loadMoreBtn.disabled = false;
                }
            }

            if (olderMessages.length > 0) {
                const fragment = document.createDocumentFragment();
                olderMessages.forEach(msg => {
                    fragment.appendChild(renderMessageDiv(msg));
                });
                
                if (loadMoreContainer && loadMoreContainer.parentNode === chatHistory) {
                    chatHistory.insertBefore(fragment, loadMoreContainer.nextSibling);
                } else {
                    chatHistory.insertBefore(fragment, chatHistory.firstChild);
                }

                // Preserve exact scroll position so the view doesn't jump
                chatHistory.scrollTop = (chatHistory.scrollHeight - prevScrollHeight) + prevScrollTop;
            }
        } catch (e) {
            console.error("Error loading earlier messages:", e);
            if (loadMoreBtn) {
                loadMoreBtn.innerHTML = '<i class="ph ph-warning mr-1"></i> Failed to load. Retry?';
                loadMoreBtn.disabled = false;
            }
        } finally {
            currentChatPagination.isLoading = false;
        }
    }

    function setupChatScrollListener() {
        const chatHistory = document.getElementById('chat-history');
        if (!chatHistory) return;
        let scrollTimeout = null;
        chatHistory.addEventListener('scroll', () => {
            if (scrollTimeout) return;
            scrollTimeout = setTimeout(() => {
                scrollTimeout = null;
                if (chatHistory.scrollTop < 60 && currentChatPagination.hasMore && !currentChatPagination.isLoading) {
                    loadEarlierMessages();
                }
            }, 150);
        });
    }

    function setupChatExport() {
        const btnExportChat = document.getElementById('btn-export-chat');
        if (btnExportChat) {
            btnExportChat.addEventListener('click', () => {
                if (!currentChatId || currentChatHistoryData.length === 0) {
                    alert("No chat history to export.");
                    return;
                }
                
                let markdownContent = `# Chat Export: ${currentChatId}\n\n`;
                currentChatHistoryData.forEach(msg => {
                    const role = msg.role === 'assistant' ? 'Agent' : 'User';
                    markdownContent += `## ${role}\n${msg.content}\n\n---\n\n`;
                });
                
                const blob = new Blob([markdownContent], { type: 'text/markdown' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${currentChatId}-export-${new Date().toISOString().replace(/:/g, '-')}.md`;
                a.click();
                URL.revokeObjectURL(url);
            });
        }
    }

    async function fetchChatSettings(chatId) {
        if (!chatId) return;
        try {
            const res = await fetch(`/api/chats/${chatId}/settings`);
            if (res.ok) {
                const data = await res.json();
                document.getElementById('chat-model-select').value = data.model || "";
                document.getElementById('chat-project-name').value = data.project_name || "";
                document.getElementById('chat-mode-select').value = data.mode || "accept-edits";
                document.getElementById('chat-skip-permissions').checked = !!data.skip_permissions;
                document.getElementById('chat-project-rules').value = data.rules || "";
            }
        } catch (e) {
            console.error("Failed to fetch chat settings", e);
        }
    }

    function setupProjectSettings() {
        const btnSave = document.getElementById('btn-save-project-settings');
        if (btnSave) {
            btnSave.addEventListener('click', async () => {
                if (!currentChatId) return;
                const model = document.getElementById('chat-model-select').value;
                const projectName = document.getElementById('chat-project-name').value;
                const mode = document.getElementById('chat-mode-select').value;
                const skipPerms = document.getElementById('chat-skip-permissions').checked;
                try {
                    btnSave.classList.add('is-loading');
                    const res = await fetch(`/api/chats/${currentChatId}/settings`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ model: model, project_name: projectName, mode: mode, skip_permissions: skipPerms })
                    });
                    if (res.ok) {
                        alert("Project settings saved successfully!");
                        document.getElementById('chat-title').textContent = projectName;
                        loadChatHistory(currentChatId); // reload history to show the logged message
                        fetchChats(); // Refresh sidebar names
                    } else {
                        throw new Error("Failed to save project settings");
                    }
                } catch (e) {
                    console.error(e);
                    alert("Error: " + e.message);
                } finally {
                    btnSave.classList.remove('is-loading');
                }
            });
        }
    }

    function setupWebChat() {
        const sendBtn = document.getElementById('chat-send-btn');
        const inputField = document.getElementById('chat-input-field');
        const chatHistory = document.getElementById('chat-history');

        async function sendMessage() {
            const text = inputField.value.trim();
            if (!text) return;
            
            let channel_id;
            if (!currentChatId) {
                // Start a new native Web Console chat
                channel_id = `portal-${Date.now()}`;
                currentChatId = `web_${channel_id}_main`;
                
                const titleEl = document.getElementById('chat-title');
                if (titleEl) titleEl.textContent = `web-${channel_id}`;
                const iconEl = document.getElementById('chat-platform-icon');
                if (iconEl) iconEl.className = 'ph ph-globe mr-2';
                chatHistory.innerHTML = '';
            } else {
                const parts = currentChatId.split('_');
                channel_id = parts[1] || 'web-portal';
            }
            
            // Clear input
            inputField.value = '';
            
            // Optimistically append user message to UI
            const msgDiv = document.createElement('div');
            msgDiv.className = 'box chat-bubble-user mb-3';
            msgDiv.innerHTML = `${getUserHeaderHtml()}${text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')}`;
            if (chatHistory.querySelector('.has-text-grey')) {
                chatHistory.innerHTML = ''; // clear empty state
            }
            chatHistory.appendChild(msgDiv);
            chatHistory.scrollTop = chatHistory.scrollHeight;

            try {
                const res = await fetch('/api/chat/invoke', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        prompt: text,
                        channel_id: channel_id
                    })
                });
                
                if (!res.ok) throw new Error("Failed to invoke agent");
                appendLog(`Dispatched message to AgentManager via WebProvider`, 'action');
                
            } catch (e) {
                console.error(e);
                appendLog(`WebProvider Error: ${e.message}`, 'error');
            }
        }

        sendBtn.addEventListener('click', sendMessage);
        inputField.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });
    }

    function setupContextMerge() {
        const mergeBtn = document.getElementById('btn-merge-context');
        const modal = document.getElementById('modal-merge');
        const modalBg = modal.querySelector('.modal-background');
        const cancelBtn = document.getElementById('btn-merge-cancel');
        const confirmBtn = document.getElementById('btn-merge-confirm');
        const targetInput = document.getElementById('input-merge-target');

        function openModal() {
            if (!currentChatId) return;
            targetInput.value = '';
            modal.classList.add('is-active');
        }

        function closeModal() {
            modal.classList.remove('is-active');
        }

        async function confirmMerge() {
            const targetId = targetInput.value.trim();
            if (!targetId || !currentChatId) return;

            try {
                confirmBtn.classList.add('is-loading');
                const res = await fetch(`/api/chats/${currentChatId}/merge`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ target_conversation_id: targetId })
                });

                if (!res.ok) throw new Error("Merge API failed");
                appendLog(`Merged network context [${currentChatId}] into [${targetId}]`, 'action');
                closeModal();
            } catch (e) {
                console.error(e);
                alert("Failed to merge context: " + e.message);
            } finally {
                confirmBtn.classList.remove('is-loading');
            }
        }

        mergeBtn.addEventListener('click', openModal);
        modalBg.addEventListener('click', closeModal);
        cancelBtn.addEventListener('click', closeModal);
        confirmBtn.addEventListener('click', confirmMerge);
    }

    function setupChatFork() {
        const forkBtn = document.getElementById('btn-fork-chat');
        if (forkBtn) {
            forkBtn.addEventListener('click', async () => {
                if (!currentChatId) return;
                
                if (!confirm("Are you sure you want to fork this project into a new one?")) return;
                
                try {
                    forkBtn.classList.add('is-loading');
                    const res = await fetch(`/api/chats/${currentChatId}/fork`, {
                        method: 'POST'
                    });
                    
                    if (!res.ok) throw new Error("Fork API failed");
                    const data = await res.json();
                    
                    appendLog(`Forked project context [${currentChatId}] into [${data.new_context_id}]`, 'action');
                    alert(`Project forked successfully! New Context ID: ${data.new_context_id}`);
                    
                    // Refresh chat list so it appears
                    fetchChats();
                    
                } catch (e) {
                    console.error(e);
                    alert("Failed to fork project: " + e.message);
                } finally {
                    forkBtn.classList.remove('is-loading');
                }
            });
        }
    }

    // 6. Export Telemetry
    function setupTelemetryExport() {
        const btnExport = document.getElementById('btn-export-telemetry');
        if (btnExport) {
            btnExport.addEventListener('click', () => {
                const logs = Array.from(logContainer.querySelectorAll('.log-entry')).map(entry => {
                    return entry.textContent;
                }).join('\n');
                
                const blob = new Blob([logs], { type: 'text/plain' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `ganymede-telemetry-${new Date().toISOString().replace(/:/g, '-')}.txt`;
                a.click();
                URL.revokeObjectURL(url);
            });
        }
    }

    // 7. Settings Config Editor
    function setupConfigEditor() {
        const editor = document.getElementById('config-editor');
        const btnSave = document.getElementById('btn-save-config');
        const btnReload = document.getElementById('btn-reload-config');
        
        const globalModelSelect = document.getElementById('global-model-select');
        const globalSystemInstructions = document.getElementById('global-system-instructions');
        const btnSaveGlobal = document.getElementById('btn-save-global-settings');
        
        let loadedConfig = null;

        if (!editor || !btnSave || !btnReload) return;

        async function loadModels() {
            try {
                const res = await fetch('/api/models');
                if (res.ok) {
                    const data = await res.json();
                    if (data.models && data.models.length > 0) {
                        const globalSel = document.getElementById('global-model-select');
                        const chatSel = document.getElementById('chat-model-select');
                        
                        const buildOptions = (sel, addDefault) => {
                            if (!sel) return;
                            const currentVal = sel.value;
                            sel.innerHTML = '';
                            if (addDefault) {
                                const opt = document.createElement('option');
                                opt.value = "";
                                opt.textContent = "Default (Global Config)";
                                sel.appendChild(opt);
                            }
                            data.models.forEach(m => {
                                const opt = document.createElement('option');
                                opt.value = m;
                                opt.textContent = m;
                                sel.appendChild(opt);
                            });
                            // Restore previous value if possible
                            if (currentVal) sel.value = currentVal;
                        };
                        
                        buildOptions(globalSel, false);
                        buildOptions(chatSel, true);
                    }
                }
            } catch (e) {
                console.error("Failed to load models list", e);
            }
        }

        async function loadConfig() {
            try {
                editor.value = "Loading config...";
                await loadModels(); // Load models first so the dropdown has options
                const res = await fetch('/api/config');
                if (!res.ok) throw new Error("Failed to load config");
                const data = await res.json();
                loadedConfig = data;
                editor.value = JSON.stringify(data, null, 2);
                
                if (data.agent) {
                    if (globalModelSelect) {
                        // Ensure the model exists in the dropdown, if not add it
                        if (data.agent.model && !Array.from(globalModelSelect.options).find(o => o.value === data.agent.model)) {
                            const opt = document.createElement('option');
                            opt.value = data.agent.model;
                            opt.textContent = data.agent.model + " (Unknown)";
                            globalModelSelect.appendChild(opt);
                        }
                        globalModelSelect.value = data.agent.model || "";
                    }
                    if (globalSystemInstructions) globalSystemInstructions.value = data.bot?.identity || "";
                    const globalBotName = document.getElementById('global-bot-name');
                    if (globalBotName) globalBotName.value = data.agent.name || "Agent";
                    const globalMissionStatement = document.getElementById('global-mission-statement');
                    if (globalMissionStatement) globalMissionStatement.value = data.agent.mission_statement || "";
                    const globalModeSelect = document.getElementById('global-mode-select');
                    if (globalModeSelect) globalModeSelect.value = data.agent.mode || "accept-edits";
                    const globalSkipPermissions = document.getElementById('global-skip-permissions');
                    if (globalSkipPermissions) globalSkipPermissions.checked = data.agent.skip_permissions !== false;
                }
            } catch (e) {
                console.error(e);
                editor.value = "Error loading config: " + e.message;
            }
        }

        async function saveConfigData(data, btn) {
            try {
                btn.classList.add('is-loading');
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (!res.ok) throw new Error("Failed to save config");
                alert("Configuration saved successfully!");
                // Refresh status metrics to reflect changes
                fetchStatus(); 
                loadConfig(); // Reload to update both UIs
            } catch (e) {
                console.error(e);
                alert("Invalid configuration JSON or save failed: " + e.message);
            } finally {
                btn.classList.remove('is-loading');
            }
        }

        btnReload.addEventListener('click', loadConfig);
        btnSave.addEventListener('click', () => {
            try {
                const text = editor.value;
                const data = JSON.parse(text);
                saveConfigData(data, btnSave);
            } catch (e) {
                alert("Invalid JSON format in the editor.");
            }
        });
        
        if (btnSaveGlobal) {
            btnSaveGlobal.addEventListener('click', () => {
                if (!loadedConfig) return;
                if (!loadedConfig.agent) loadedConfig.agent = {};
                
                const modelVal = globalModelSelect.value;
                if (modelVal) loadedConfig.agent.model = modelVal;
                else delete loadedConfig.agent.model;
                
                if (!loadedConfig.bot) loadedConfig.bot = {};
                loadedConfig.bot.identity = globalSystemInstructions.value;
                
                const globalBotName = document.getElementById('global-bot-name');
                if (globalBotName && globalBotName.value) {
                    loadedConfig.agent.name = globalBotName.value;
                } else {
                    delete loadedConfig.agent.name;
                }
                
                const globalMissionStatement = document.getElementById('global-mission-statement');
                if (globalMissionStatement && globalMissionStatement.value) {
                    loadedConfig.agent.mission_statement = globalMissionStatement.value;
                }
                
                const globalModeSelect = document.getElementById('global-mode-select');
                if (globalModeSelect) {
                    loadedConfig.agent.mode = globalModeSelect.value;
                }
                
                const globalSkipPermissions = document.getElementById('global-skip-permissions');
                if (globalSkipPermissions) {
                    loadedConfig.agent.skip_permissions = globalSkipPermissions.checked;
                }
                
                saveConfigData(loadedConfig, btnSaveGlobal);
            });
        }

        // Load initially
        window.loadConfig = loadConfig;
        loadConfig();
    }

    // Live Subagents & Active Tasks Tracker
    const activeSubagents = new Map();

    function updateSubagentUI() {
        const container = document.getElementById('subagents-list');
        const emptyState = document.getElementById('subagents-empty-state');
        if (!container || !emptyState) return;

        if (activeSubagents.size === 0) {
            emptyState.classList.remove('is-hidden');
            container.innerHTML = '';
            return;
        }

        emptyState.classList.add('is-hidden');
        container.innerHTML = '';

        activeSubagents.forEach((subagent, id) => {
            const card = document.createElement('div');
            card.className = 'subagent-card';
            const isRunning = subagent.status === 'running';
            const statusBadgeClass = isRunning ? 'subagent-status-running' : 'subagent-status-idle';
            const statusIcon = isRunning ? '🟢' : '⚪';

            card.innerHTML = `
                <div class="subagent-header">
                    <div>
                        <strong class="is-size-6 cinzel">${subagent.role || 'Subagent'}</strong>
                        <span class="has-text-grey ml-2 is-size-7 font-mono">${id.slice(0, 14)}</span>
                    </div>
                    <span class="subagent-status-badge ${statusBadgeClass}">
                        ${statusIcon} ${subagent.status.toUpperCase()}
                    </span>
                </div>
                <div class="is-size-7 mb-2">
                    <span class="has-text-grey">Model:</span> <strong>${subagent.model || 'Gemini 3.7 Flash'}</strong>
                    <span class="has-text-grey ml-3">Current Action:</span> <span class="tag is-small is-light">${subagent.lastTool || 'None'}</span>
                </div>
                ${subagent.actionSummary ? `<p class="is-size-7 mb-0 font-mono" style="background: var(--bg-surface-alt); color: var(--text-main); padding: 6px; border-radius: 4px; border: 1px solid var(--border-subtle);">↳ ${subagent.actionSummary}</p>` : ''}
            `;
            container.appendChild(card);
        });
    }

    function setupDashboardCenterTabs() {
        const tabs = document.querySelectorAll('#dashboard-center-tabs li');
        const telemetryContent = document.getElementById('tab-telemetry-content');
        const subagentsContent = document.getElementById('tab-subagents-content');

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('is-active'));
                tab.classList.add('is-active');
                const target = tab.getAttribute('data-tab');
                if (target === 'tab-telemetry') {
                    telemetryContent?.classList.remove('is-hidden');
                    subagentsContent?.classList.add('is-hidden');
                } else if (target === 'tab-subagents') {
                    telemetryContent?.classList.add('is-hidden');
                    subagentsContent?.classList.remove('is-hidden');
                    updateSubagentUI();
                }
            });
        });
    }

    let currentArtifactsList = [];
    let selectedArtifactPath = null;
    let selectedArtifactContent = "";

    function setupArtifactsModal() {
        const btnViewArtifacts = document.getElementById('btn-view-artifacts');
        const modal = document.getElementById('modal-artifacts');
        const fileListEl = document.getElementById('file-list');
        const filterInput = document.getElementById('artifact-filter');
        const previewContent = document.getElementById('artifact-preview-content');
        const previewFilename = document.getElementById('preview-filename');
        const previewSize = document.getElementById('preview-size');
        const btnOpen = document.getElementById('btn-open-local-artifact');
        const btnCopy = document.getElementById('btn-copy-artifact');
        const btnDownload = document.getElementById('btn-download-artifact');

        async function loadArtifacts() {
            if (!currentChatId) return;
            fileListEl.innerHTML = '<li class="has-text-grey is-size-7 p-3 text-center">Loading artifacts...</li>';
            try {
                const res = await fetch(`/api/chats/${currentChatId}/files`);
                if (!res.ok) throw new Error("Failed to load artifacts");
                const data = await res.json();
                currentArtifactsList = data.files || [];
                renderArtifactList(currentArtifactsList);
            } catch (err) {
                fileListEl.innerHTML = `<li class="has-text-danger is-size-7 p-3">Error: ${err.message}</li>`;
            }
        }

        function renderArtifactList(files) {
            fileListEl.innerHTML = '';
            if (files.length === 0) {
                fileListEl.innerHTML = '<li class="has-text-grey is-size-7 p-3 text-center">No artifacts found in this project.</li>';
                previewFilename.textContent = "No files";
                previewSize.textContent = "--";
                previewContent.innerHTML = '<div class="has-text-centered has-text-grey mt-6"><p>No generated artifacts found.</p></div>';
                return;
            }

            files.forEach(file => {
                const li = document.createElement('li');
                li.className = `artifact-item ${file.path === selectedArtifactPath ? 'is-selected' : ''}`;
                
                const isMd = file.name.endsWith('.md');
                const isCode = file.name.endsWith('.py') || file.name.endsWith('.json') || file.name.endsWith('.gd') || file.name.endsWith('.swift');
                const iconClass = isMd ? 'ph-file-text' : (isCode ? 'ph-file-code' : 'ph-file');

                li.innerHTML = `
                    <div class="is-flex is-align-items-center" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        <span class="icon is-small mr-2 text-grey"><i class="ph ${iconClass}"></i></span>
                        <span class="is-size-7 font-mono">${file.name}</span>
                    </div>
                    <span class="tag is-light is-small ml-1">${formatBytes(file.size)}</span>
                `;

                li.addEventListener('click', () => {
                    selectArtifact(file);
                });

                fileListEl.appendChild(li);
            });

            // If nothing is selected or current selection not in list, select the first
            const hasSelected = files.some(f => f.path === selectedArtifactPath);
            if (!hasSelected && files.length > 0) {
                selectArtifact(files[0]);
            }
        }

        async function selectArtifact(file) {
            selectedArtifactPath = file.path;
            
            // Update highlights
            Array.from(fileListEl.querySelectorAll('.artifact-item')).forEach((el, i) => {
                if (currentArtifactsList[i] && currentArtifactsList[i].path === file.path) {
                    el.classList.add('is-selected');
                } else {
                    el.classList.remove('is-selected');
                }
            });

            previewFilename.textContent = file.name;
            previewSize.textContent = formatBytes(file.size);
            previewContent.innerHTML = '<div class="has-text-centered has-text-grey mt-6"><span class="icon is-medium ph-spin"><i class="ph ph-spinner fa-lg"></i></span><p>Loading file content...</p></div>';

            try {
                const res = await fetch(`/api/chats/${currentChatId}/file_content?path=${encodeURIComponent(file.path)}`);
                if (!res.ok) throw new Error("Failed to read file content");
                const data = await res.json();
                selectedArtifactContent = data.content;
                selectedArtifactAbsolutePath = data.absolute_path || null;

                if (file.name.endsWith('.md')) {
                    previewContent.innerHTML = formatAgentMarkdown(data.content);
                } else {
                    previewContent.innerHTML = `<pre style="background: #1e1e2e; color: #cdd6f4; padding: 14px; border-radius: 6px; font-size: 0.82rem; max-height: 100%; overflow-y: auto;"><code>${data.content.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</code></pre>`;
                }
            } catch (err) {
                previewContent.innerHTML = `<div class="notification is-danger is-light">${err.message}</div>`;
            }
        }

        if (filterInput) {
            filterInput.addEventListener('input', (e) => {
                const q = e.target.value.toLowerCase();
                const filtered = currentArtifactsList.filter(f => f.name.toLowerCase().includes(q) || f.path.toLowerCase().includes(q));
                renderArtifactList(filtered);
            });
        }

        if (btnOpen) {
            btnOpen.addEventListener('click', async () => {
                if (selectedArtifactAbsolutePath) {
                    try {
                        const res = await fetch('/api/open_file', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ path: selectedArtifactAbsolutePath })
                        });
                        if (res.ok) {
                            const orig = btnOpen.innerHTML;
                            btnOpen.innerHTML = '<span class="icon is-small has-text-success"><i class="ph ph-check"></i></span><span>Opened</span>';
                            setTimeout(() => { btnOpen.innerHTML = orig; }, 1500);
                        }
                    } catch (err) {
                        console.error("Failed to open file:", err);
                    }
                }
            });
        }

        if (btnCopy) {
            btnCopy.addEventListener('click', () => {
                if (selectedArtifactContent) {
                    navigator.clipboard.writeText(selectedArtifactContent).then(() => {
                        const originalText = btnCopy.innerHTML;
                        btnCopy.innerHTML = '<span class="icon is-small"><i class="ph ph-check"></i></span><span>Copied!</span>';
                        setTimeout(() => { btnCopy.innerHTML = originalText; }, 1500);
                    });
                }
            });
        }

        if (btnDownload) {
            btnDownload.addEventListener('click', () => {
                if (selectedArtifactContent && selectedArtifactPath) {
                    const blob = new Blob([selectedArtifactContent], { type: 'text/plain' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = previewFilename.textContent || 'artifact.txt';
                    a.click();
                    URL.revokeObjectURL(url);
                }
            });
        }

        const btnToggleArtifactSidebar = document.getElementById('btn-toggle-artifact-sidebar');
        const btnToggleArtifactSidebarText = document.getElementById('btn-toggle-artifact-sidebar-text');
        const artifactSidebarPane = document.getElementById('artifact-sidebar-pane');

        if (btnToggleArtifactSidebar && artifactSidebarPane) {
            btnToggleArtifactSidebar.addEventListener('click', () => {
                artifactSidebarPane.classList.toggle('is-hidden');
                const isHidden = artifactSidebarPane.classList.contains('is-hidden');
                if (btnToggleArtifactSidebarText) {
                    btnToggleArtifactSidebarText.textContent = isHidden ? 'Show List' : 'Hide List';
                }
                btnToggleArtifactSidebar.classList.toggle('is-active-toggle', isHidden);
            });
        }

        if (btnViewArtifacts) {
            btnViewArtifacts.addEventListener('click', () => {
                if (currentChatId) {
                    modal.classList.add('is-active');
                    loadArtifacts();
                }
            });
        }
    }

    // Intercept clicking on any file:/// links to trigger opening in native macOS editor/IDE
    document.addEventListener('click', (e) => {
        const fileLink = e.target.closest('a[href^="file://"]');
        if (fileLink) {
            e.preventDefault();
            const filePath = fileLink.getAttribute('href');
            fetch('/api/open_file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: filePath })
            }).catch(err => console.error("Failed to open file link:", err));
        }
    });

    // Initialize
    async function fetchUserInfo() {
        try {
            const res = await fetch('/api/user');
            if (res.ok) {
                userInfo = await res.json();
                const badgeAvatar = document.querySelector('.account-badge .avatar');
                const badgeTitle = document.querySelector('.account-badge .title');
                if (badgeAvatar && userInfo.avatar_url) {
                    badgeAvatar.innerHTML = `<img src="${userInfo.avatar_url}" referrerpolicy="no-referrer" style="width: 100%; height: 100%; border-radius: 50%;">`;
                }
                if (badgeTitle && userInfo.name) {
                    badgeTitle.textContent = userInfo.name;
                }
            }
        } catch (e) {
            console.error("Failed to fetch user info", e);
        }
    }
    
    fetchUserInfo();
    fetchStatus();
    setInterval(fetchStatus, 5000); // Live updates for header and metrics
    fetchChats();
    connectWebSocket();
    setupPanes();
    setupWebChat();
    setupContextMerge();
    setupChatFork();
    setupTelemetryExport();
    setupConfigEditor();
    setupChatTabs();
    setupSettingsTabs();
    setupArtifactsModal();
    setupDashboardCenterTabs();
    setupChatExport();
    setupChatScrollListener();
    setupProjectSettings();
    setupRulesEditor();
    setupRouting();
    
    // Rules & Workflows Editor
    function setupRulesEditor() {
        const ruleList = document.getElementById('rule-list');
        const ruleFilename = document.getElementById('rule-filename');
        const ruleEditor = document.getElementById('rule-editor');
        const btnNew = document.getElementById('btn-new-rule');
        const btnSave = document.getElementById('btn-save-rule');
        const btnDelete = document.getElementById('btn-delete-rule');
        
        let currentRule = null;
        
        async function loadRules() {
            try {
                const res = await fetch('/api/rules');
                if (!res.ok) return;
                const data = await res.json();
                
                ruleList.innerHTML = '';
                if (data.rules && data.rules.length > 0) {
                    data.rules.forEach(rule => {
                        const li = document.createElement('li');
                        const a = document.createElement('a');
                        a.textContent = rule;
                        if (rule === currentRule) a.classList.add('is-active');
                        
                        a.addEventListener('click', () => selectRule(rule));
                        li.appendChild(a);
                        ruleList.appendChild(li);
                    });
                } else {
                    ruleList.innerHTML = '<li><a class="has-text-grey">No rules found</a></li>';
                }
            } catch (e) {
                console.error("Failed to load rules", e);
            }
        }
        
        async function selectRule(filename) {
            try {
                const res = await fetch(`/api/rules?filename=${encodeURIComponent(filename)}`);
                if (!res.ok) throw new Error("Failed to load rule");
                const data = await res.json();
                
                currentRule = filename;
                ruleFilename.value = filename;
                ruleFilename.disabled = true;
                ruleEditor.value = data.content || '';
                ruleEditor.disabled = false;
                btnSave.disabled = false;
                btnDelete.disabled = false;
                
                loadRules(); // Update active state
            } catch (e) {
                console.error("Error selecting rule", e);
            }
        }
        
        btnNew.addEventListener('click', () => {
            currentRule = null;
            ruleFilename.value = 'new_rule.md';
            ruleFilename.disabled = false;
            ruleEditor.value = '<RULE[new_rule]>\n\n</RULE[new_rule]>';
            ruleEditor.disabled = false;
            btnSave.disabled = false;
            btnDelete.disabled = true;
            
            // Remove active class from list
            ruleList.querySelectorAll('a').forEach(a => a.classList.remove('is-active'));
        });
        
        btnSave.addEventListener('click', async () => {
            const filename = ruleFilename.value.trim();
            if (!filename || !filename.endsWith('.md')) {
                alert("Filename must end with .md");
                return;
            }
            
            btnSave.classList.add('is-loading');
            try {
                const res = await fetch('/api/rules', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        filename: filename,
                        content: ruleEditor.value
                    })
                });
                
                if (res.ok) {
                    currentRule = filename;
                    ruleFilename.disabled = true;
                    btnDelete.disabled = false;
                    await loadRules();
                } else {
                    const data = await res.json();
                    alert("Error saving: " + data.error);
                }
            } catch (e) {
                console.error("Failed to save rule", e);
            } finally {
                btnSave.classList.remove('is-loading');
            }
        });
        
        btnDelete.addEventListener('click', async () => {
            if (!currentRule) return;
            if (!confirm(`Are you sure you want to delete ${currentRule}?`)) return;
            
            btnDelete.classList.add('is-loading');
            try {
                const res = await fetch(`/api/rules/${encodeURIComponent(currentRule)}`, {
                    method: 'DELETE'
                });
                
                if (res.ok) {
                    currentRule = null;
                    ruleFilename.value = '';
                    ruleFilename.disabled = true;
                    ruleEditor.value = '';
                    ruleEditor.disabled = true;
                    btnSave.disabled = true;
                    btnDelete.disabled = true;
                    await loadRules();
                }
            } catch (e) {
                console.error("Failed to delete rule", e);
            } finally {
                btnDelete.classList.remove('is-loading');
            }
        });
        
        // Initial load
        window.loadRules = loadRules;
        loadRules();
    }
    
    // Poll for new chats and files periodically
    setInterval(() => {
        if (currentChatId) fetchChatFiles(currentChatId);
    }, 30000);
    setInterval(fetchChats, 10000);
    
    // ==========================================
    // AGENTS & CHANNEL ROUTING CONTROLLERS
    // ==========================================

    let cachedAvailableModels = [];
    let cachedAgents = {};
    let cachedChannelMappings = {};
    let cachedChannels = [];

    async function fetchAvailableModels() {
        if (cachedAvailableModels.length > 0) return cachedAvailableModels;
        try {
            const res = await fetch('/api/models');
            if (res.ok) {
                const data = await res.json();
                cachedAvailableModels = data.models || [];
            }
        } catch (e) {
            console.error('Failed to load models list', e);
            cachedAvailableModels = ["Gemini 3.7 Flash (High)", "Gemini 3.1 Pro (High)"];
        }
        return cachedAvailableModels;
    }

    async function populateModelDropdown(selectEl, selectedValue) {
        if (!selectEl) return;
        const models = await fetchAvailableModels();
        selectEl.innerHTML = '';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            if (selectedValue && (selectedValue.toLowerCase() === m.toLowerCase() || selectedValue.toLowerCase() === m.toLowerCase().replace(/ /g, '-'))) {
                opt.selected = true;
            }
            selectEl.appendChild(opt);
        });
        if (!selectEl.value && models.length > 0) {
            selectEl.value = selectedValue || models[0];
        }
    }

    async function loadAgents() {
        const grid = document.getElementById('agents-list');
        if (!grid) return;
        grid.innerHTML = '<div class="column is-12 has-text-centered has-text-grey py-5"><span class="icon is-large mb-2"><i class="ph ph-spinner ph-spin fa-2x"></i></span><p>Loading agents...</p></div>';

        try {
            const [agentsRes, channelsRes] = await Promise.all([
                fetch('/api/agents'),
                fetch('/api/channels')
            ]);

            if (agentsRes.ok) {
                const data = await agentsRes.json();
                cachedAgents = data.agents || {};
                cachedChannelMappings = data.channel_mappings || {};
            }
            if (channelsRes.ok) {
                const cData = await channelsRes.json();
                cachedChannels = cData.channels || [];
            }

            grid.innerHTML = '';

            const agentEntries = Object.entries(cachedAgents);
            if (agentEntries.length === 0) {
                grid.innerHTML = '<div class="column is-12 has-text-centered has-text-grey py-5"><p>No custom agents defined. Click <strong>New Agent</strong> to create one.</p></div>';
                return;
            }

            for (const [agentId, agent] of agentEntries) {
                // Count bound channels
                let boundChannelsCount = 0;
                for (const ch of cachedChannels) {
                    if (ch.assigned_agent_id === agentId) {
                        boundChannelsCount++;
                    }
                }

                const displayName = agent.name || agentId;
                const modelName = agent.model || 'Gemini 3.7 Flash (High)';
                const workspacePath = agent.workspace || '~/dev';
                const modeName = agent.mode || 'accept-edits';
                const isDefault = (agentId === 'default');

                const html = `
                <div class="column is-4">
                    <div class="card facet is-clickable" onclick="window.location.hash='#view-agent-detail?id=' + encodeURIComponent('${agentId}'); if (window.handleRoute) window.handleRoute('#view-agent-detail?id=' + encodeURIComponent('${agentId}'));" style="height: 100%; transition: transform 0.2s ease, box-shadow 0.2s ease;">
                        <div class="card-content is-flex is-flex-direction-column" style="height: 100%;">
                            <div class="is-flex is-align-items-center mb-3">
                                <span class="icon is-large has-text-primary mr-3" style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; background: rgba(50, 115, 220, 0.1); border-radius: 50%;">
                                    <i class="ph ph-robot fa-2x"></i>
                                </span>
                                <div>
                                    <h3 class="title is-5 cinzel mb-0">${displayName}</h3>
                                    <p class="subtitle is-7 has-text-grey font-mono">@${agentId} ${isDefault ? '<span class="tag is-primary is-light is-small ml-1">Default</span>' : ''}</p>
                                </div>
                            </div>
                            
                            <p class="is-size-7 has-text-grey mb-3" style="overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; min-height: 2.4em;">
                                ${agent.mission_statement || 'Custom autonomous agent for Ganymede.'}
                            </p>

                            <div class="mt-auto pt-3" style="border-top: 1px solid var(--border-marble); width: 100%;">
                                <div class="is-flex is-justify-content-space-between is-align-items-center mb-2">
                                    <span class="has-text-grey is-size-7">Model</span>
                                    <span class="tag is-info is-light is-small">${modelName}</span>
                                </div>
                                <div class="is-flex is-justify-content-space-between is-align-items-center mb-2">
                                    <span class="has-text-grey is-size-7">Workspace</span>
                                    <span class="is-size-7 font-mono has-text-weight-semibold" style="max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${workspacePath}</span>
                                </div>
                                <div class="is-flex is-justify-content-space-between is-align-items-center">
                                    <span class="has-text-grey is-size-7">Channels</span>
                                    <span class="tag is-small ${boundChannelsCount > 0 ? 'is-success is-light' : 'is-light'}">${boundChannelsCount} bound</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>`;
                grid.insertAdjacentHTML('beforeend', html);
            }
        } catch (e) {
            console.error('Failed to load agents', e);
            grid.innerHTML = '<div class="column is-12 has-text-centered has-text-danger py-5"><p>Failed to load agents list.</p></div>';
        }
    }

    async function loadAgentDetails(agentId) {
        try {
            const [agentsRes, channelsRes] = await Promise.all([
                fetch('/api/agents'),
                fetch('/api/channels')
            ]);

            let agents = {};
            let channelMappings = {};
            if (agentsRes.ok) {
                const data = await agentsRes.json();
                agents = data.agents || {};
                channelMappings = data.channel_mappings || {};
            }

            let channels = [];
            if (channelsRes.ok) {
                const cData = await channelsRes.json();
                channels = cData.channels || [];
            }

            let agent = agents[agentId];
            const isNew = (agentId === 'new' || !agent);
            if (isNew) {
                agent = {
                    id: '',
                    name: 'New Agent',
                    model: 'Gemini 3.7 Flash (High)',
                    workspace: '~/dev',
                    mode: 'accept-edits',
                    skip_permissions: true,
                    identity: 'You are {bot_name}. Mission: {mission_statement}.',
                    mission_statement: 'assisting with engineering tasks',
                    bindings: []
                };
            }

            // Populate form fields
            document.getElementById('agent-detail-title').textContent = agent.name || 'New Agent';
            document.getElementById('agent-detail-id-label').textContent = isNew ? 'Create New Agent Profile' : `@${agentId}`;
            
            const idInput = document.getElementById('agent-input-id');
            idInput.value = isNew ? '' : agentId;
            idInput.disabled = (!isNew && agentId === 'default');

            document.getElementById('agent-input-name').value = agent.name || '';
            document.getElementById('agent-input-workspace').value = agent.workspace || '~/dev';
            document.getElementById('agent-select-mode').value = agent.mode || 'accept-edits';
            document.getElementById('agent-skip-permissions').checked = (agent.skip_permissions !== false);
            document.getElementById('agent-input-mission').value = agent.mission_statement || '';
            document.getElementById('agent-input-identity').value = agent.identity || '';

            // Populate dynamic models
            await populateModelDropdown(document.getElementById('agent-select-model'), agent.model || 'Gemini 3.7 Flash (High)');

            // Delete button state
            const deleteBtn = document.getElementById('btn-delete-agent');
            if (deleteBtn) {
                deleteBtn.style.display = (isNew || agentId === 'default') ? 'none' : '';
            }

            // Populate Channel Bindings Checkboxes
            const bindingsContainer = document.getElementById('agent-channel-bindings-container');
            if (bindingsContainer) {
                bindingsContainer.innerHTML = '';
                if (channels.length === 0) {
                    bindingsContainer.innerHTML = '<p class="has-text-grey is-size-7 has-text-centered py-3">No active platform channels discovered yet. Connect Discord to see live channels.</p>';
                } else {
                    channels.forEach(ch => {
                        const key = `${ch.platform}:${ch.id}`;
                        const isAssigned = (ch.assigned_agent_id === agentId) || (channelMappings[key] === agentId);
                        
                        const itemDiv = document.createElement('div');
                        itemDiv.className = 'field mb-2 is-flex is-align-items-center is-justify-content-space-between p-2';
                        itemDiv.style.borderRadius = '4px';
                        itemDiv.style.backgroundColor = isAssigned ? 'rgba(50, 115, 220, 0.08)' : 'transparent';
                        
                        itemDiv.innerHTML = `
                            <label class="checkbox is-size-7 is-flex is-align-items-center">
                                <input type="checkbox" class="channel-binding-cb mr-2" data-platform="${ch.platform}" data-channel-id="${ch.id}" ${isAssigned ? 'checked' : ''}>
                                <span><strong>#${ch.name}</strong> <span class="has-text-grey">(${ch.guild_name || ch.platform})</span></span>
                            </label>
                            <span class="tag is-small is-light">${ch.id}</span>
                        `;
                        bindingsContainer.appendChild(itemDiv);
                    });
                }
            }

        } catch (e) {
            console.error('Failed to load agent details', e);
        }
    }

    async function loadChannels() {
        const tbody = document.getElementById('channels-table-body');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="6" class="has-text-centered has-text-grey py-5"><span class="icon mr-2"><i class="ph ph-spinner ph-spin"></i></span>Loading channels...</td></tr>';

        try {
            const [channelsRes, agentsRes] = await Promise.all([
                fetch('/api/channels'),
                fetch('/api/agents')
            ]);

            let channels = [];
            let agents = {};
            if (channelsRes.ok) {
                const cData = await channelsRes.json();
                channels = cData.channels || [];
            }
            if (agentsRes.ok) {
                const aData = await agentsRes.json();
                agents = aData.agents || {};
            }

            tbody.innerHTML = '';

            if (channels.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="has-text-centered has-text-grey py-5">No channels discovered yet. Make sure Discord bot is running.</td></tr>';
                return;
            }

            channels.forEach(ch => {
                const tr = document.createElement('tr');
                tr.dataset.platform = ch.platform || 'discord';
                tr.dataset.channelId = ch.id || '';
                tr.dataset.guildId = ch.guild_id || '';
                
                // Build agent options
                let agentOptions = '';
                for (const [aid, adata] of Object.entries(agents)) {
                    const isSelected = (ch.assigned_agent_id === aid);
                    agentOptions += `<option value="${aid}" ${isSelected ? 'selected' : ''}>${adata.name || aid} (@${aid})</option>`;
                }

                tr.innerHTML = `
                    <td><span class="tag is-info is-light is-capitalized"><i class="ph ph-discord-logo mr-1"></i>${ch.platform}</span></td>
                    <td><strong>${ch.guild_name || 'Direct / Global'}</strong></td>
                    <td><span class="tag is-dark is-small mr-1">#</span><strong>${ch.name}</strong> <span class="is-size-7 has-text-grey">(${ch.id})</span></td>
                    <td class="is-size-7 has-text-grey" style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${ch.topic || '—'}</td>
                    <td>
                        <div class="select is-small is-fullwidth">
                            <select class="channel-agent-select" data-platform="${ch.platform}" data-channel-id="${ch.id}">
                                ${agentOptions}
                            </select>
                        </div>
                    </td>
                    <td>
                        <a href="#view-agent-detail?id=${encodeURIComponent(ch.assigned_agent_id || 'default')}" class="button is-small is-light" title="Edit Assigned Agent">
                            <span class="icon is-small"><i class="ph ph-sliders"></i></span>
                        </a>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            // Add click listener to Edit Agent buttons
            tbody.querySelectorAll('a[href^="#view-agent-detail"]').forEach(link => {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    window.location.hash = link.getAttribute('href');
                    if (window.handleRoute) window.handleRoute();
                });
            });

            // Add change listener to channel agent selects
            document.querySelectorAll('.channel-agent-select').forEach(sel => {
                sel.addEventListener('change', async (e) => {
                    const platform = e.target.dataset.platform;
                    const channelId = e.target.dataset.channelId;
                    const agentId = e.target.value;
                    sel.disabled = true;
                    
                    try {
                        const res = await fetch('/api/channels/assign', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ platform, channel_id: channelId, agent_id: agentId })
                        });
                        if (res.ok) {
                            sel.classList.add('is-success');
                            setTimeout(() => sel.classList.remove('is-success'), 1500);
                        }
                    } catch (err) {
                        console.error('Failed to assign agent', err);
                        alert('Failed to assign agent to channel');
                    } finally {
                        sel.disabled = false;
                    }
                });
            });

        } catch (e) {
            console.error('Failed to load channels', e);
            tbody.innerHTML = '<tr><td colspan="6" class="has-text-centered has-text-danger py-5">Failed to load channels.</td></tr>';
        }
    }

    // Agent Creation & Save Event Listeners
    const btnCreateAgent = document.getElementById('btn-create-agent');
    if (btnCreateAgent) {
        btnCreateAgent.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.hash = '#view-agent-detail?id=new';
            if (window.handleRoute) window.handleRoute('#view-agent-detail?id=new');
        });
    }

    const btnBackToAgents = document.getElementById('btn-back-to-agents');
    if (btnBackToAgents) {
        btnBackToAgents.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.hash = '#view-agents';
            if (window.handleRoute) window.handleRoute('#view-agents');
        });
    }

    const btnSaveAgent = document.getElementById('btn-save-agent');
    if (btnSaveAgent) {
        btnSaveAgent.addEventListener('click', async () => {
            const rawId = document.getElementById('agent-input-id').value.trim();
            if (!rawId) {
                alert('Please enter an Agent ID (e.g. rotor, devops, default)');
                return;
            }
            const agentId = rawId.toLowerCase().replace(/[^a-z0-9_-]/g, '_');
            const name = document.getElementById('agent-input-name').value.trim() || agentId;
            const model = document.getElementById('agent-select-model').value;
            const workspace = document.getElementById('agent-input-workspace').value.trim() || '~/dev';
            const mode = document.getElementById('agent-select-mode').value;
            const skipPermissions = document.getElementById('agent-skip-permissions').checked;
            const missionStatement = document.getElementById('agent-input-mission').value.trim();
            const identity = document.getElementById('agent-input-identity').value;

            // Collect bound channels
            const boundChannels = [];
            document.querySelectorAll('.channel-binding-cb:checked').forEach(cb => {
                boundChannels.push({
                    platform: cb.dataset.platform,
                    channel_id: cb.dataset.channelId
                });
            });

            btnSaveAgent.classList.add('is-loading');

            try {
                // Save Agent
                const agentData = {
                    id: agentId,
                    name: name,
                    model: model,
                    workspace: workspace,
                    mode: mode,
                    skip_permissions: skipPermissions,
                    mission_statement: missionStatement,
                    identity: identity,
                    bindings: [{ provider: 'discord', channels: boundChannels.map(b => b.channel_id) }]
                };

                const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(agentData)
                });

                if (res.ok) {
                    // Update channel bindings individually
                    for (const b of boundChannels) {
                        await fetch('/api/channels/assign', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ platform: b.platform, channel_id: b.channel_id, agent_id: agentId })
                        });
                    }

                    btnSaveAgent.classList.remove('is-loading');
                    btnSaveAgent.classList.add('is-success');
                    btnSaveAgent.textContent = 'Saved!';
                    setTimeout(() => {
                        btnSaveAgent.classList.remove('is-success');
                        btnSaveAgent.textContent = 'Save Changes';
                        window.location.hash = '#view-agents';
                        if (window.handleRoute) window.handleRoute();
                    }, 1200);
                } else {
                    const err = await res.json();
                    alert(err.error || 'Failed to save agent');
                    btnSaveAgent.classList.remove('is-loading');
                }
            } catch (e) {
                console.error('Failed to save agent', e);
                alert('Network error while saving agent');
                btnSaveAgent.classList.remove('is-loading');
            }
        });
    }

    const btnDeleteAgent = document.getElementById('btn-delete-agent');
    if (btnDeleteAgent) {
        btnDeleteAgent.addEventListener('click', async () => {
            const agentId = document.getElementById('agent-input-id').value.trim();
            if (!agentId || agentId === 'default') {
                alert('Cannot delete the default agent');
                return;
            }
            if (!confirm(`Are you sure you want to delete agent '@${agentId}'?`)) {
                return;
            }

            btnDeleteAgent.classList.add('is-loading');
            try {
                const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}`, {
                    method: 'DELETE'
                });
                if (res.ok) {
                    window.location.hash = '#view-agents';
                    if (window.handleRoute) window.handleRoute();
                } else {
                    const err = await res.json();
                    alert(err.error || 'Failed to delete agent');
                }
            } catch (e) {
                console.error('Failed to delete agent', e);
            } finally {
                btnDeleteAgent.classList.remove('is-loading');
            }
        });
    }

    // Search filter for channels view
    const channelsSearch = document.getElementById('channels-search-input');
    if (channelsSearch) {
        channelsSearch.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            const rows = document.querySelectorAll('#channels-table-body tr');
            rows.forEach(row => {
                if (row.children.length === 1) return;
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(query) ? '' : 'none';
            });
        });
    }
});

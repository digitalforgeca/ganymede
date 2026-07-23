document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const statusText = document.getElementById("status-text");
    const pulse = document.querySelector(".pulse");
    
    const valPlatform = document.getElementById("val-platform");
    const valLoglevel = document.getElementById("val-loglevel");
    const valDatadir = document.getElementById("val-datadir");
    
    const fileList = document.getElementById("file-list");
    const logContainer = document.getElementById("log-container");

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
            const avatarHtml = userInfo.avatar_url ? `<img src="${userInfo.avatar_url}" referrerpolicy="no-referrer" style="width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px;">` : `<svg style="width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px; background: #ddd; fill: #666; padding: 4px;" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>`;
            return `<div style="margin-bottom: 8px; display: flex; align-items: center;">
                        ${avatarHtml}
                        <strong>${userInfo.name}</strong>
                    </div>`;
        }
        const defaultUserIcon = `<svg style="width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px; background: #ddd; fill: #666; padding: 4px;" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>`;
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
                
                // Handle streaming to active chat
                if (data.context && data.context === currentChatId) {
                    if (data.event === "Agent Stream Start") {
                        const msgDiv = document.createElement('div');
                        msgDiv.className = 'box has-background-light mb-3';
                        msgDiv.id = data.payload.msg_id;
                        let safeContent = data.payload.content || "⏳ *Thinking...*";
                        if (window.marked) safeContent = marked.parse(safeContent);
                        else safeContent = safeContent.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
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
                            if (window.marked) safeContent = marked.parse(safeContent);
                            else safeContent = safeContent.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
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
        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        
        const time = new Date().toLocaleTimeString();
        entry.innerHTML = `<span class="log-time">[${time}]</span><span class="log-msg">${message}</span>`;
        
        logContainer.appendChild(entry);
        
        // Auto scroll to bottom
        if (logContainer.children.length > 200) {
            logContainer.removeChild(logContainer.firstChild); // Keep memory bounded
        }
        logContainer.scrollTop = logContainer.scrollHeight;
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

        function handleRoute() {
            let hash = window.location.hash;
            if (!hash) {
                hash = '#view-dashboard';
                // Don't replace state, just let it fall through
            }
            
            // Extract the base view id (e.g., #view-bots?botId=xxx -> view-bots)
            let targetId = hash.substring(1).split('?')[0];
            if (!document.getElementById(targetId)) {
                targetId = 'view-dashboard';
            }
            
            // Remove active class from all nav items
            navItems.forEach(nav => nav.classList.remove('is-active'));
            
            // Add active class to clicked item (match by data-target)
            const activeNav = document.querySelector(`.sidebar-nav .nav-item[data-target="${targetId}"]`);
            if (activeNav) activeNav.classList.add('is-active');
            
            // Hide all views
            views.forEach(view => view.classList.add('is-hidden'));
            
            // Show target view
            const targetView = document.getElementById(targetId);
            if (targetView) {
                targetView.classList.remove('is-hidden');
            }
            
            // Trigger specific actions based on the view
            if (targetId === 'view-bots') {
                loadBots();
            } else if (targetId === 'view-chats') {
                const params = new URLSearchParams(hash.split('?')[1] || '');
                if (params.has('chat') && window.selectChatById) {
                    window.selectChatById(params.get('chat'));
                }
                if (params.has('tab') && window.selectChatTab) {
                    window.selectChatTab(params.get('tab'));
                } else if (window.selectChatTab) {
                    window.selectChatTab('chat');
                }
            } else if (targetId === 'view-bot-detail') {
                const params = new URLSearchParams(hash.split('?')[1] || '');
                const botId = params.get('id');
                if (botId) {
                    loadBotDetails(botId);
                }
            } else if (targetId === 'view-settings') {
                const params = new URLSearchParams(hash.split('?')[1] || '');
                if (params.has('tab') && window.selectSettingsTab) {
                    window.selectSettingsTab(params.get('tab'));
                } else if (window.selectSettingsTab) {
                    window.selectSettingsTab('global');
                }
            }
        }

        window.addEventListener('hashchange', handleRoute);
        
        // Initial route handling
        handleRoute();
    }

    function setupPanes() {
        const toggleBtn = document.getElementById('btn-toggle-channels');
        const channelsPane = document.getElementById('channels-pane');
        const handleChannels = document.getElementById('handle-channels');
        
        if (toggleBtn && channelsPane) {
            toggleBtn.addEventListener('click', () => {
                channelsPane.classList.toggle('is-hidden');
            });
        }
        
        const mainToggleBtn = document.getElementById('main-sidebar-toggle');
        const olympusSidebar = document.querySelector('.olympus-sidebar');
        const mainContent = document.querySelector('.main-content');
        const handleMain = document.getElementById('handle-main');
        
        if (mainToggleBtn && olympusSidebar && mainContent) {
            mainToggleBtn.addEventListener('click', () => {
                olympusSidebar.classList.toggle('is-hidden');
            });
        }
        
        function makeResizable(pane, handle) {
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
                const newWidth = startWidth + (e.clientX - startX);
                pane.style.width = `${newWidth}px`;
            });
            
            document.addEventListener('mouseup', () => {
                if (isResizing) {
                    isResizing = false;
                    handle.classList.remove('is-dragging');
                    document.body.style.cursor = '';
                }
            });
        }
        
        makeResizable(channelsPane, handleChannels);
        makeResizable(olympusSidebar, handleMain);
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
            tab.addEventListener('click', () => {
                const target = tab.dataset.tab;
                const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
                params.set('tab', target);
                window.location.hash = `#view-chats?${params.toString()}`;
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
        
        viewGlobal.classList.add('is-hidden');
        viewRules.classList.add('is-hidden');
        viewRaw.classList.add('is-hidden');
        
        if (target === 'global') {
            viewGlobal.classList.remove('is-hidden');
        } else if (target === 'rules') {
            viewRules.classList.remove('is-hidden');
        } else if (target === 'raw') {
            viewRaw.classList.remove('is-hidden');
        }
    };

    function setupSettingsTabs() {
        const tabList = document.querySelectorAll('#settings-tabs-container li');
        tabList.forEach(tab => {
            tab.addEventListener('click', () => {
                window.location.hash = `#view-settings?tab=${tab.dataset.tab}`;
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
            
            li.appendChild(a);
            chatList.appendChild(li);
        });
    }

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
            } else {
                document.getElementById('chat-list').innerHTML = '<li><a>No active projects found.</a></li>';
            }
        } catch (e) {
            console.error(e);
            document.getElementById('chat-list').innerHTML = '<li><a>Error loading projects</a></li>';
        }
    }
    
    async function loadChatHistory(chatId) {
        const chatHistory = document.getElementById('chat-history');
        chatHistory.innerHTML = '<div class="has-text-centered has-text-grey mt-5">Loading history...</div>';
        
        try {
            const res = await fetch(`/api/chats/${chatId}/history`);
            if (!res.ok) throw new Error("Failed to load chat history");
            const data = await res.json();
            
            currentChatHistoryData = data.messages || [];
            
            chatHistory.innerHTML = '';
            if (currentChatHistoryData.length > 0) {
                currentChatHistoryData.forEach(msg => {
                    const msgDiv = document.createElement('div');
                    msgDiv.className = `box mb-3 ${msg.role === 'assistant' ? 'has-background-light' : 'has-background-white'}`;
                    
                    // Convert markdown to HTML using marked.js
                    let safeContent = "";
                    if (window.marked) {
                        safeContent = marked.parse(msg.content);
                    } else {
                        safeContent = msg.content.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
                    }
                    
                    const roleLabel = msg.role === 'assistant' ? getAgentHeaderHtml() : getUserHeaderHtml();
                    msgDiv.innerHTML = `${roleLabel}${safeContent}`;
                    
                    chatHistory.appendChild(msgDiv);
                });
            } else {
                chatHistory.innerHTML = '<div class="has-text-centered has-text-grey mt-5">No history yet. Say hello!</div>';
            }
            chatHistory.scrollTop = chatHistory.scrollHeight;
        } catch (e) {
            console.error(e);
            chatHistory.innerHTML = `<div class="has-text-centered has-text-danger mt-5">Error: ${e.message}</div>`;
        }
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
                
                // Set up UI for the new chat
                document.getElementById('chat-title').textContent = `web-${channel_id}`;
                document.getElementById('chat-platform-icon').className = 'ph ph-globe';
                chatHistory.innerHTML = '';
            } else {
                const parts = currentChatId.split('_');
                channel_id = parts[1] || 'web-portal';
            }
            
            // Clear input
            inputField.value = '';
            
            // Optimistically append user message to UI
            const msgDiv = document.createElement('div');
            msgDiv.className = 'box has-background-white mb-3';
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
        loadConfig();
    }

    function setupArtifactsModal() {
        const btnViewArtifacts = document.getElementById('btn-view-artifacts');
        if (btnViewArtifacts) {
            btnViewArtifacts.addEventListener('click', () => {
                if (currentChatId) {
                    document.getElementById('modal-artifacts').classList.add('is-active');
                }
            });
        }
    }

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
    setupRouting();
    setupPanes();
    setupWebChat();
    setupContextMerge();
    setupChatFork();
    setupTelemetryExport();
    setupConfigEditor();
    setupChatTabs();
    setupSettingsTabs();
    setupArtifactsModal();
    setupChatExport();
    setupProjectSettings();
    setupRulesEditor();
    
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
        loadRules();
    }
    
    // Poll for new chats and files periodically
    setInterval(() => {
        if (currentChatId) fetchChatFiles(currentChatId);
    }, 30000);
    setInterval(fetchChats, 10000);
    
    // Hamburger menu toggle for mobile
    const mainToggleBtn = document.getElementById('main-sidebar-toggle');
    const olympusSidebar = document.querySelector('.olympus-sidebar');
    if (mainToggleBtn && olympusSidebar) {
        mainToggleBtn.addEventListener('click', () => {
            olympusSidebar.classList.toggle('is-mobile-active');
            if (olympusSidebar.style.display === 'none' || olympusSidebar.style.display === '') {
                olympusSidebar.style.display = 'block';
            } else {
                olympusSidebar.style.display = 'none';
            }
        });
    }
});

    async function loadBots() {
        try {
            const res = await fetch('/api/bots');
            if (res.ok) {
                const data = await res.json();
                const bots = data.bots;
                
                const botsGrid = document.getElementById('bots-list');
                if (!botsGrid) return;
                botsGrid.innerHTML = ''; // Clear hardcoded
                
                for (const [botId, botData] of Object.entries(bots)) {
                    const platformType = botData.provider?.type || 'discord';
                    
                    const html = `
                    <div class="column is-4">
                        <div class="card is-clickable metric" onclick="window.location.hash='#view-bot-detail?id=' + encodeURIComponent('${botId}')">
                            <div class="card-content">
                                <div class="media">
                                    <div class="media-left">
                                        <figure class="image is-48x48">
                                            <span class="icon is-large has-text-info"><i class="ph ph-robot" style="font-size: 2rem;"></i></span>
                                        </figure>
                                    </div>
                                    <div class="media-content">
                                        <p class="title is-4">${botData.name || botId}</p>
                                        <p class="subtitle is-6">@${botId}</p>
                                    </div>
                                </div>
                                <div class="content">
                                    <div class="tags">
                                        <span class="tag is-info is-light">Provider: ${platformType}</span>
                                        <span class="tag is-primary is-light">Model: ${botData.model || 'Default'}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>`;
                    botsGrid.insertAdjacentHTML('beforeend', html);
                }
            }
        } catch (e) {
            console.error('Failed to load bots from API', e);
        }
    }

    async function loadBotDetails(botId) {
        // Load the system prompt and mission from config
        try {
            const configRes = await fetch('/api/config');
            if (configRes.ok) {
                const configData = await configRes.json();
                document.getElementById('bot-detail-name').textContent = configData.agent?.name || botId || 'Ganymede';
                document.getElementById('bot-system-prompt').value = configData.bot?.identity || '';
            }
            
            // Load conversations
            const convRes = await fetch('/api/chats');
            if (convRes.ok) {
                const chatsData = await convRes.json();
                const list = document.getElementById('bot-conversations-list');
                list.innerHTML = '';
                
                if (chatsData.length === 0) {
                    list.innerHTML = '<tr><td colspan="4" class="has-text-centered has-text-grey">No conversations found.</td></tr>';
                } else {
                    chatsData.forEach(conv => {
                        const tr = document.createElement('tr');
                        
                        let dateStr = 'Unknown';
                        if (conv.last_active) {
                            if (typeof conv.last_active === 'number') {
                                dateStr = new Date(conv.last_active * 1000).toLocaleString();
                            } else {
                                dateStr = new Date(conv.last_active + (conv.last_active.endsWith('Z') ? '' : 'Z')).toLocaleString();
                            }
                        }
                        
                        tr.innerHTML = `
                            <td>${conv.project_name || conv.platform}</td>
                            <td><span class="tag is-light is-small">${conv.id}</span></td>
                            <td class="is-size-7">${dateStr}</td>
                            <td><a href="#view-chats?chat=${encodeURIComponent(conv.id)}" class="button is-small is-light">View</a></td>
                        `;
                        list.appendChild(tr);
                    });
                }
            }
        } catch (e) {
            console.error('Failed to load bot details', e);
        }
    }

    document.getElementById('btn-save-bot-prompt').addEventListener('click', async () => {
        const prompt = document.getElementById('bot-system-prompt').value;
        const btn = document.getElementById('btn-save-bot-prompt');
        btn.classList.add('is-loading');
        
        try {
            // First fetch existing config to preserve other fields
            const configRes = await fetch('/api/config');
            let data = {};
            if (configRes.ok) {
                data = await configRes.json();
            }
            
            if (!data.bot) data.bot = {};
            data.bot.identity = prompt;
            
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            
            if (res.ok) {
                btn.classList.remove('is-info', 'is-loading');
                btn.classList.add('is-success');
                btn.textContent = 'Saved!';
                setTimeout(() => {
                    btn.classList.remove('is-success');
                    btn.classList.add('is-info');
                    btn.textContent = 'Save Prompt';
                }, 2000);
            }
        } catch (e) {
            console.error(e);
            alert('Failed to save prompt');
            btn.classList.remove('is-loading');
        }
    });

    // Add search listener for bot conversations
    document.getElementById('bot-conversations-search').addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        const rows = document.querySelectorAll('#bot-conversations-list tr');
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            if (text.includes(query)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    });

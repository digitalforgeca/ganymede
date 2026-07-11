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
            const avatarHtml = botInfo.avatar_url ? `<img src="${botInfo.avatar_url}" style="width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px;">` : '';
            return `<div style="margin-bottom: 8px; display: flex; align-items: center;">
                        ${avatarHtml}
                        <strong>${botInfo.name}</strong>
                        <span class="has-text-grey ml-2 is-size-7" style="font-family: monospace;">(${botInfo.id})</span>
                    </div>`;
        }
        return `<strong>Agent:</strong><br>`;
    }

    // 1. Fetch Configuration API
    async function fetchStatus() {
        try {
            const res = await fetch('/api/status');
            if (!res.ok) throw new Error("Status API failed");
            const data = await res.json();
            
            valPlatform.textContent = data.platform || "Unknown";
            valLoglevel.textContent = data.log_level || "Unknown";
            valDatadir.textContent = data.data_dir || "Unknown";
            
            if (data.metrics) {
                document.getElementById('metric-active-instances').textContent = data.metrics.active_instances || 0;
                document.getElementById('metric-tokens-hour').textContent = data.metrics.tokens_hour || 0;
                document.getElementById('metric-quota-text').textContent = `${data.metrics.quota_used} / ${data.metrics.quota_limit} reqs`;
                const pct = (data.metrics.quota_used / Math.max(1, data.metrics.quota_limit)) * 100;
                document.getElementById('metric-quota-bar').value = pct;
            }
            
            if (data.bot_info) {
                botInfo = data.bot_info;
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

        navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                
                // Remove active class from all nav items
                navItems.forEach(nav => nav.classList.remove('is-active'));
                
                // Add active class to clicked item
                e.target.classList.add('is-active');
                
                // Hide all views
                views.forEach(view => view.classList.add('is-hidden'));
                
                // Show target view
                const targetId = e.target.getAttribute('data-target');
                const targetView = document.getElementById(targetId);
                if (targetView) {
                    targetView.classList.remove('is-hidden');
                }
            });
        });
    }

    // 5. Native Web Chat Invocation
    let currentChatId = null;
    
    async function fetchChats() {
        try {
            const res = await fetch('/api/chats');
            if (!res.ok) throw new Error("Failed to load chats");
            const data = await res.json();
            
            const chatList = document.getElementById('chat-list');
            if (data.chats && data.chats.length > 0) {
                // Group by platform
                const groups = {};
                data.chats.forEach(chat => {
                    if (!groups[chat.platform]) groups[chat.platform] = [];
                    groups[chat.platform].push(chat);
                });
                
                // Build tabs
                const tabsList = document.getElementById('project-tabs');
                if (tabsList) {
                    let activeTab = document.querySelector('#project-tabs li.is-active')?.dataset?.platform;
                    if (!activeTab || !groups[activeTab]) {
                        activeTab = Object.keys(groups)[0];
                    }
                    
                    tabsList.innerHTML = '';
                    Object.keys(groups).forEach(platform => {
                        const li = document.createElement('li');
                        li.dataset.platform = platform;
                        if (platform === activeTab) li.classList.add('is-active');
                        li.innerHTML = `<a><span>${platform.toUpperCase()}</span></a>`;
                        li.addEventListener('click', () => {
                            document.querySelectorAll('#project-tabs li').forEach(el => el.classList.remove('is-active'));
                            li.classList.add('is-active');
                            renderChats(groups[platform]);
                        });
                        tabsList.appendChild(li);
                    });
                    
                    renderChats(groups[activeTab]);
                } else {
                    renderChats(data.chats);
                }
                
                function renderChats(chatsToRender) {
                    chatList.innerHTML = '';
                    chatsToRender.forEach(chat => {
                        const li = document.createElement('li');
                        const a = document.createElement('a');
                        a.className = "is-flex is-justify-content-space-between is-align-items-center";
                        const displayName = chat.project_name || `${chat.platform}-${chat.channel_id}${chat.thread_id ? `-${chat.thread_id}` : ''}`;
                        a.innerHTML = `
                            <span>
                                <span class="icon is-small"><i class="fas ${chat.platform === 'discord' ? 'fa-discord' : 'fa-terminal'}"></i></span>
                                <span class="chat-name">${displayName}</span>
                                <span class="is-size-7 has-text-grey ml-1">(${chat.platform === 'discord' ? '#' : ''}${chat.channel_id})</span>
                            </span>
                            <span class="tag is-dark is-rounded">${chat.msg_count}</span>
                        `;
                        
                        if (currentChatId === chat.id) {
                            a.classList.add('is-active');
                        }
                        
                        a.addEventListener('click', (e) => {
                            e.preventDefault();
                            document.querySelectorAll('#chat-list a').forEach(el => el.classList.remove('is-active'));
                            a.classList.add('is-active');
                            currentChatId = chat.id;
                            document.getElementById('chat-title').textContent = displayName;
                            document.getElementById('chat-subtitle').textContent = `Platform: ${chat.platform} | Channel: ${chat.channel_id}`;
                            document.getElementById('btn-export-chat').classList.remove('is-hidden');
                            document.getElementById('btn-view-artifacts').classList.remove('is-hidden');
                            document.getElementById('btn-merge-context').classList.remove('is-hidden');
                            loadChatHistory(chat.id);
                            fetchChatFiles(chat.id);
                            fetchChatSettings(chat.id);
                        });
                        
                        li.appendChild(a);
                        chatList.appendChild(li);
                    });
                }
            } else {
                chatList.innerHTML = '<li><a>No active projects found.</a></li>';
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
                    
                    const roleLabel = msg.role === 'assistant' ? getAgentHeaderHtml() : '<strong>You:</strong><br>';
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
                try {
                    btnSave.classList.add('is-loading');
                    const res = await fetch(`/api/chats/${currentChatId}/settings`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ model: model, project_name: projectName })
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
            
            if (!currentChatId) {
                alert("Please select or start a chat first.");
                return;
            }
            
            const parts = currentChatId.split('_');
            const channel_id = parts[1] || 'web-portal';
            
            // Clear input
            inputField.value = '';
            
            // Optimistically append user message to UI
            const msgDiv = document.createElement('div');
            msgDiv.className = 'box has-background-white mb-3';
            msgDiv.innerHTML = `<strong>You:</strong><br>${text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')}`;
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

        async function loadConfig() {
            try {
                editor.value = "Loading config...";
                const res = await fetch('/api/config');
                if (!res.ok) throw new Error("Failed to load config");
                const data = await res.json();
                loadedConfig = data;
                editor.value = JSON.stringify(data, null, 2);
                
                if (data.agent) {
                    if (globalModelSelect) globalModelSelect.value = data.agent.model || "";
                    if (globalSystemInstructions) globalSystemInstructions.value = data.agent.system_instructions || "";
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
                
                loadedConfig.agent.system_instructions = globalSystemInstructions.value;
                
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
    fetchStatus();
    fetchChats();
    connectWebSocket();
    setupRouting();
    setupWebChat();
    setupContextMerge();
    setupTelemetryExport();
    setupConfigEditor();
    setupChatTabs();
    setupArtifactsModal();
    setupChatExport();
    setupProjectSettings();
    
    // Poll for new chats and files periodically
    setInterval(() => {
        if (currentChatId) fetchChatFiles(currentChatId);
    }, 30000);
    setInterval(fetchChats, 10000);
});

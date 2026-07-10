document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const statusText = document.getElementById("status-text");
    const pulse = document.querySelector(".pulse");
    
    const valPlatform = document.getElementById("val-platform");
    const valLoglevel = document.getElementById("val-loglevel");
    const valDatadir = document.getElementById("val-datadir");
    const valWorkspace = document.getElementById("val-workspace");
    
    const fileList = document.getElementById("file-list");
    const logContainer = document.getElementById("log-container");

    let ws = null;

    // Format bytes to human readable
    function formatBytes(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
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
            
            setOnline(true);
        } catch (e) {
            console.error("Failed to fetch status", e);
            setOnline(false);
        }
    }

    // 2. Fetch Brain Files API
    async function fetchFiles() {
        try {
            const res = await fetch('/api/files');
            if (!res.ok) throw new Error("Files API failed");
            const data = await res.json();
            
            valWorkspace.textContent = data.workspace || "Not Configured";
            
            fileList.innerHTML = '';
            if (data.files && data.files.length > 0) {
                data.files.forEach(f => {
                    const li = document.createElement('li');
                    li.innerHTML = `<span class="file-name">${f.name}</span><span class="file-size">${formatBytes(f.size)}</span>`;
                    // Could add click handler here to open file via a new API if needed
                    fileList.appendChild(li);
                });
            } else {
                fileList.innerHTML = '<li class="empty-state">No files found in workspace.</li>';
            }
        } catch (e) {
            console.error("Failed to fetch files", e);
            fileList.innerHTML = '<li class="empty-state">Error loading artifacts.</li>';
        }
    }

    // 3. Connect to Telemetry WebSocket API
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;
        
        ws = new WebSocket(wsUrl);
        
        ws.onopen = () => {
            appendLog('Connected to Ganymede Telemetry Stream.', 'system');
            setOnline(true);
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
            } catch (e) {
                appendLog(event.data, 'event');
            }
        };
        
        ws.onclose = () => {
            setOnline(false);
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
            chatList.innerHTML = '';
            
            if (data.chats && data.chats.length > 0) {
                data.chats.forEach(chat => {
                    const li = document.createElement('li');
                    const a = document.createElement('a');
                    const threadInfo = chat.thread_id ? ` / ${chat.thread_id}` : '';
                    a.textContent = `${chat.platform} - ${chat.channel_id}${threadInfo}`;
                    
                    if (currentChatId === chat.id) {
                        a.classList.add('is-active');
                    }
                    
                    a.addEventListener('click', () => {
                        document.querySelectorAll('#chat-list a').forEach(el => el.classList.remove('is-active'));
                        a.classList.add('is-active');
                        currentChatId = chat.id;
                        document.getElementById('chat-title').textContent = `${chat.platform} - ${chat.channel_id}`;
                        document.getElementById('chat-subtitle').textContent = `Thread: ${chat.thread_id || 'main'}`;
                        document.getElementById('btn-merge-context').classList.remove('is-hidden');
                        loadChatHistory(chat.id);
                    });
                    
                    li.appendChild(a);
                    chatList.appendChild(li);
                });
            } else {
                chatList.innerHTML = '<li><a>No active chats found.</a></li>';
            }
        } catch (e) {
            console.error(e);
            document.getElementById('chat-list').innerHTML = '<li><a>Error loading chats</a></li>';
        }
    }
    
    async function loadChatHistory(chatId) {
        const chatHistory = document.getElementById('chat-history');
        chatHistory.innerHTML = '<div class="has-text-centered has-text-grey mt-5">Loading history...</div>';
        
        try {
            const res = await fetch(`/api/chats/${chatId}/history`);
            if (!res.ok) throw new Error("Failed to load chat history");
            const data = await res.json();
            
            chatHistory.innerHTML = '';
            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(msg => {
                    const msgDiv = document.createElement('div');
                    msgDiv.className = `box mb-3 ${msg.role === 'assistant' ? 'has-background-light' : 'has-background-white'}`;
                    
                    // Convert markdown to minimal HTML for safety, but for now just plain text
                    const safeContent = msg.content.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
                    
                    msgDiv.innerHTML = `<strong>${msg.role === 'assistant' ? 'Agent' : 'User'}:</strong><br>${safeContent}`;
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

    // Initialize
    fetchStatus();
    fetchFiles();
    fetchChats();
    connectWebSocket();
    setupRouting();
    setupWebChat();
    setupContextMerge();
    
    // Poll for new files and chats periodically
    setInterval(fetchFiles, 30000);
    setInterval(fetchChats, 10000);
});

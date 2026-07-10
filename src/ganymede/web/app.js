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

    // Initialize
    fetchStatus();
    fetchFiles();
    connectWebSocket();
    
    // Poll for new files every 30s
    setInterval(fetchFiles, 30000);
});

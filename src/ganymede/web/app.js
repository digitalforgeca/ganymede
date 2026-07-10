document.addEventListener('DOMContentLoaded', () => {
    const statusText = document.getElementById('status-text');
    const platformVal = document.getElementById('platform-val');
    const logLevelVal = document.getElementById('log-level-val');
    const dataDirVal = document.getElementById('data-dir-val');
    const uptimeVal = document.getElementById('uptime-val');
    const refreshBtn = document.getElementById('refresh-btn');
    const statusIndicator = document.querySelector('.status-indicator');

    let startTime = Date.now();

    function updateUptime() {
        const diff = Date.now() - startTime;
        const seconds = Math.floor((diff / 1000) % 60);
        const minutes = Math.floor((diff / (1000 * 60)) % 60);
        const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);

        const h = hours > 0 ? `${hours}h ` : '';
        const m = minutes > 0 ? `${minutes}m ` : '';
        const s = `${seconds}s`;

        uptimeVal.textContent = h + m + s;
    }

    setInterval(updateUptime, 1000);

    async function fetchStatus() {
        try {
            refreshBtn.textContent = 'Refreshing...';
            const response = await fetch('/api/status');
            if (response.ok) {
                const data = await response.json();
                
                statusText.textContent = 'System Online';
                statusIndicator.classList.remove('status-offline');
                
                platformVal.textContent = data.platform || 'Unknown';
                logLevelVal.textContent = data.log_level || 'INFO';
                dataDirVal.textContent = data.data_dir || '--';
            } else {
                throw new Error('API Error');
            }
        } catch (error) {
            statusText.textContent = 'Offline';
            statusIndicator.classList.add('status-offline');
            platformVal.textContent = '--';
            logLevelVal.textContent = '--';
        } finally {
            refreshBtn.textContent = 'Refresh Status';
        }
    }

    refreshBtn.addEventListener('click', fetchStatus);

    // Initial fetch
    fetchStatus();
});

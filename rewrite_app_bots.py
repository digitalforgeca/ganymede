import re
with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/themes/default/app.js', 'r') as f:
    content = f.read()
    
# Remove old loadBots
content = re.sub(r'    async function loadBots\(\).*?(?=    async function loadBotDetails\()', '', content, flags=re.DOTALL)

# Remove old loadBotDetails
content = re.sub(r'    async function loadBotDetails\(botId\).*?(?=    document\.getElementById\(\'btn-save-bot-prompt\'\))', '', content, flags=re.DOTALL)

# Remove old btn-save-bot-prompt listener
content = re.sub(r'    document\.getElementById\(\'btn-save-bot-prompt\'\)\.addEventListener\(\'click\', async \(\) => \{.*?(?=    // Add search listener for bot conversations)', '', content, flags=re.DOTALL)

new_code = """
    // Global to keep track of current bot in detail view
    let currentBotDetailId = null;

    async function loadBots() {
        try {
            const res = await fetch('/api/bots');
            if (res.ok) {
                const data = await res.json();
                const bots = data.bots;
                
                const botsGrid = document.getElementById('bots-grid');
                if (!botsGrid) return;
                botsGrid.innerHTML = '';
                
                for (const [botId, botData] of Object.entries(bots)) {
                    const platformType = botData.provider?.type || 'discord';
                    
                    const html = `
                    <div class="column is-4">
                        <div class="card is-clickable metric" onclick="window.location.hash='#view-bot-detail?id=' + encodeURIComponent('${botId}')">
                            <div class="card-content">
                                <div class="media">
                                    <div class="media-left">
                                        <figure class="image is-48x48">
                                            <span class="icon is-large has-text-info"><i class="fas fa-robot fa-2x"></i></span>
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
        if (!botId) return;
        currentBotDetailId = botId;
        try {
            const res = await fetch(`/api/bots/${botId}`);
            if (!res.ok) throw new Error("Failed to load bot config");
            const data = await res.json();
            const botData = data.bot;
            
            document.getElementById('bot-detail-name').textContent = botData.name || botId;
            document.getElementById('bot-setting-name').value = botData.name || '';
            document.getElementById('bot-setting-model').value = botData.model || '';
            document.getElementById('bot-system-prompt').value = botData.identity || '';
            
            const providerType = botData.provider?.type || 'discord';
            document.getElementById('bot-provider-type-label').textContent = providerType;
            
            // Build dynamic fields from provider schema
            const provRes = await fetch('/api/providers');
            if (provRes.ok) {
                const provData = await provRes.json();
                const providerInfo = provData.providers.find(p => p.id === providerType);
                const fieldsContainer = document.getElementById('bot-provider-fields');
                fieldsContainer.innerHTML = '';
                
                if (providerInfo && providerInfo.schema) {
                    for (const [key, details] of Object.entries(providerInfo.schema)) {
                        const val = botData.provider[key] || '';
                        fieldsContainer.innerHTML += `
                            <div class="field">
                                <label class="label is-small">${details.description || key}</label>
                                <div class="control">
                                    <input class="input is-small provider-field" data-key="${key}" type="${details.type === 'bool' ? 'checkbox' : 'text'}" ${details.type === 'bool' && val ? 'checked' : ''} value="${details.type !== 'bool' ? val : ''}">
                                </div>
                            </div>
                        `;
                    }
                }
            }
            
            // Load conversations
            const convRes = await fetch('/api/chats');
            if (convRes.ok) {
                const chatsData = await convRes.json();
                const list = document.getElementById('bot-conversations-list');
                list.innerHTML = '';
                
                // Filter chats to this bot if applicable (for now show all or filter by ID if the bot maps to a specific project)
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
        if (!currentBotDetailId) return;
        const btn = document.getElementById('btn-save-bot-prompt');
        btn.classList.add('is-loading');
        
        try {
            // Reconstruct config
            const botData = {
                name: document.getElementById('bot-setting-name').value,
                model: document.getElementById('bot-setting-model').value,
                identity: document.getElementById('bot-system-prompt').value,
                provider: {
                    type: document.getElementById('bot-provider-type-label').textContent.toLowerCase()
                }
            };
            
            document.querySelectorAll('.provider-field').forEach(el => {
                const key = el.getAttribute('data-key');
                if (el.type === 'checkbox') {
                    botData.provider[key] = el.checked;
                } else {
                    botData.provider[key] = el.value;
                }
            });
            
            const res = await fetch(`/api/bots/${currentBotDetailId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(botData)
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
            alert('Failed to save config');
            btn.classList.remove('is-loading');
        }
    });

"""

# Insert before search listener
content = content.replace("    // Add search listener for bot conversations", new_code + "\n    // Add search listener for bot conversations")

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/themes/default/app.js', 'w') as f:
    f.write(content)

print("Rewrote app.js bots logic")

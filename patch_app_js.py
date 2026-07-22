import re

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/app.js', 'r') as f:
    content = f.read()

# I need to fetch providers on load
t1 = "async function fetchConfig() {"
r1 = """
let providerSchemas = {};
let allBots = {};

async function fetchProviders() {
    try {
        const res = await fetch('/api/providers');
        const data = await res.json();
        if (data.providers) {
            data.providers.forEach(p => {
                providerSchemas[p.id] = p.schema;
            });
        }
    } catch (e) {
        console.error("Failed to fetch providers", e);
    }
}

async function fetchBots() {
    try {
        const res = await fetch('/api/bots');
        const data = await res.json();
        allBots = data.bots || {};
        renderBotsList();
    } catch(e) {
        console.error("Failed to fetch bots", e);
    }
}

function renderBotsList() {
    const list = document.getElementById('bots-list');
    list.innerHTML = '';
    
    for (const [botId, botData] of Object.entries(allBots)) {
        const providerType = (botData.provider && botData.provider.type) ? botData.provider.type : "unknown";
        const name = botData.name || botId;
        
        const col = document.createElement('div');
        col.className = 'column is-4';
        col.innerHTML = `
            <div class="card is-clickable" onclick="loadBotDetail('${botId}')">
                <div class="card-content has-text-centered">
                    <div class="mb-3">
                        <figure class="image is-96x96 is-inline-block">
                            <i class="fas fa-robot fa-4x has-text-info" style="margin-top:20px;"></i>
                        </figure>
                    </div>
                    <p class="title is-4 cinzel mb-1">${name}</p>
                    <p class="subtitle is-6 has-text-grey">${botId}</p>
                    
                    <div class="mt-4 pt-4" style="border-top: 1px solid #eee;">
                        <div class="is-flex is-justify-content-space-between mb-2">
                            <span class="has-text-grey is-size-7">Platform</span>
                            <span class="has-text-info has-text-weight-bold is-size-7">${providerType}</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
        list.appendChild(col);
    }
}

let activeBotId = null;

function loadBotDetail(botId) {
    activeBotId = botId;
    const botData = allBots[botId];
    if (!botData) return;
    
    document.getElementById('bot-detail-name').textContent = botData.name || botId;
    document.getElementById('bot-setting-name').value = botData.name || '';
    document.getElementById('bot-setting-model').value = botData.model || '';
    document.getElementById('bot-system-prompt').value = botData.identity || '';
    
    const pType = (botData.provider && botData.provider.type) ? botData.provider.type : "discord";
    document.getElementById('bot-provider-type-label').textContent = pType;
    
    const container = document.getElementById('bot-provider-fields');
    container.innerHTML = '';
    
    const schema = providerSchemas[pType];
    if (schema && schema.properties) {
        for (const [key, field] of Object.entries(schema.properties)) {
            const wrapper = document.createElement('div');
            wrapper.className = 'field';
            
            const label = document.createElement('label');
            label.className = 'label is-small';
            label.textContent = field.title || key;
            wrapper.appendChild(label);
            
            const control = document.createElement('div');
            control.className = 'control';
            
            const val = (botData.provider && botData.provider[key]) !== undefined ? botData.provider[key] : '';
            
            if (field.type === 'array') {
                const input = document.createElement('input');
                input.className = 'input is-small provider-field';
                input.type = 'text';
                input.dataset.key = key;
                input.dataset.type = 'array';
                input.value = Array.isArray(val) ? val.join(', ') : val;
                input.placeholder = "Comma separated values";
                control.appendChild(input);
            } else {
                const input = document.createElement('input');
                input.className = 'input is-small provider-field';
                input.type = 'text';
                input.dataset.key = key;
                input.dataset.type = 'string';
                input.value = val;
                control.appendChild(input);
            }
            
            if (field.description) {
                const help = document.createElement('p');
                help.className = 'help has-text-grey';
                help.textContent = field.description;
                control.appendChild(help);
            }
            
            wrapper.appendChild(control);
            container.appendChild(wrapper);
        }
    } else {
        container.innerHTML = '<p class="is-size-7 has-text-grey">No additional configuration required.</p>';
    }
    
    switchView('bot-detail');
}

async function saveBotDetail() {
    if (!activeBotId) return;
    
    const btn = document.getElementById('btn-save-bot-prompt');
    btn.classList.add('is-loading');
    
    const botData = allBots[activeBotId] || { provider: {} };
    botData.name = document.getElementById('bot-setting-name').value;
    botData.model = document.getElementById('bot-setting-model').value;
    botData.identity = document.getElementById('bot-system-prompt').value;
    
    const fields = document.querySelectorAll('.provider-field');
    fields.forEach(f => {
        const key = f.dataset.key;
        if (f.dataset.type === 'array') {
            botData.provider[key] = f.value.split(',').map(s => s.trim()).filter(s => s);
        } else {
            botData.provider[key] = f.value;
        }
    });
    
    try {
        await fetch(`/api/bots/${activeBotId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(botData)
        });
        showToast("Bot settings saved!", "is-success");
        fetchBots(); // Refresh
    } catch (e) {
        showToast("Failed to save bot", "is-danger");
    } finally {
        btn.classList.remove('is-loading');
    }
}

""" + t1

if t1 in content:
    content = content.replace(t1, r1)
    
# Remove globals loading from fetchConfig
content = re.sub(r"document\.getElementById\('global-bot-name'\)\.value = [^;]+;", "", content)
content = re.sub(r"document\.getElementById\('global-model-select'\)\.value = [^;]+;", "", content)

# Remove old save bot handler and replace with new one
content = re.sub(r"document\.getElementById\('btn-save-bot-prompt'\)\.addEventListener\('click', async \(\) => \{[^}]+\}\);", 
                 "document.getElementById('btn-save-bot-prompt').addEventListener('click', saveBotDetail);", content)

# Hook up fetchProviders and fetchBots in init
init_t = "fetchConfig();"
init_r = "fetchProviders().then(() => fetchBots());\n    fetchConfig();"
if init_t in content:
    content = content.replace(init_t, init_r)

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/app.js', 'w') as f:
    f.write(content)
print("app.js patched successfully")

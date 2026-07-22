import re

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/app.js', 'r') as f:
    content = f.read()

# We want to remove the old loadBotDetails and any lingering old btn-save-bot-prompt listener
old_load = re.search(r"async function loadBotDetails\(botId\).*?}\n\n    document\.getElementById\('btn-save-bot-prompt'\)\.addEventListener\('click', saveBotDetail\);", content, re.DOTALL)
if old_load:
    content = content.replace(old_load.group(0), "")

# We need to add the conversation loading to our NEW loadBotDetail function
t = "switchView('bot-detail');\n}"
r = """
    // Load conversations
    fetch('/api/chats')
        .then(res => res.json())
        .then(chatsData => {
            const list = document.getElementById('bot-conversations-list');
            if (!list) return;
            list.innerHTML = '';
            
            if (!chatsData || chatsData.length === 0) {
                list.innerHTML = '<tr><td colspan="4" class="has-text-centered has-text-grey">No conversations found.</td></tr>';
            } else {
                // Filter chats to those that match the bot? 
                // Right now /api/chats returns all chats. We might not have a way to filter by botId on the backend easily right now unless platform matches, but let's just show all for now since Ganymede is primarily one gateway
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
        }).catch(e => console.error("Failed to load bot conversations", e));

    switchView('bot-detail');
}"""

if t in content:
    content = content.replace(t, r)
    
with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/app.js', 'w') as f:
    f.write(content)
print("Cleaned up old loadBotDetails")

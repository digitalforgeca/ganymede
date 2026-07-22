import re

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/index.html', 'r') as f:
    content = f.read()

# 1. Remove global-bot-name and global-model-select from settings
t1 = """                                    <div class="field">
                                        <label class="label is-small">Web Console Bot Name</label>
                                        <div class="control">
                                            <input class="input is-small" type="text" id="global-bot-name" placeholder="Agent">
                                        </div>
                                    </div>
                                    <div class="field">
                                        <label class="label is-small">Global Model Override</label>
                                        <div class="control">
                                            <div class="select is-small is-fullwidth">
                                                <select id="global-model-select">
                                                    <option value="">Default (System Fallback)</option>
                                                    <option value="Gemini 3.1 Pro (High)">Gemini 3.1 Pro (High) (Recommended)</option>
                                                    <option value="Gemini Flash">Gemini Flash (Fast)</option>
                                                    <option value="gemini-1.5-pro-002">gemini-1.5-pro-002</option>
                                                    <option value="gemini-1.5-flash-002">gemini-1.5-flash-002</option>
                                                </select>
                                            </div>
                                        </div>
                                    </div>"""

if t1 in content:
    content = content.replace(t1, "")

# 2. Add Name, Model, and Provider Config fields to Bot Detail view
t2 = """                                <h3 class="title is-6"><span class="icon is-small mr-2"><i class="fas fa-magic"></i></span>System Prompt</h3>"""

r2 = """
                                <h3 class="title is-6"><span class="icon is-small mr-2"><i class="fas fa-robot"></i></span>Bot Settings</h3>
                                <div class="field">
                                    <label class="label is-small">Name</label>
                                    <div class="control">
                                        <input class="input is-small" type="text" id="bot-setting-name">
                                    </div>
                                </div>
                                <div class="field">
                                    <label class="label is-small">Default Model</label>
                                    <div class="control">
                                        <input class="input is-small" type="text" id="bot-setting-model">
                                    </div>
                                </div>
                                
                                <div id="bot-provider-config-container" class="mt-4 mb-4" style="border-left: 2px solid #3273dc; padding-left: 10px;">
                                    <h4 class="title is-6 mb-2 has-text-info">Provider Settings (<span id="bot-provider-type-label"></span>)</h4>
                                    <div id="bot-provider-fields"></div>
                                </div>
                                <hr>
                                """ + t2

if t2 in content:
    content = content.replace(t2, r2)


with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/index.html', 'w') as f:
    f.write(content)
print("index.html patched")

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/themes/default/index.html', 'r') as f:
    content = f.read()

target = """                        <div class="columns is-multiline" id="bots-list">
                            <!-- Populated by JS -->
                            <div class="column is-4">
                                <div class="card" id="primary-bot-card">
                                    <div class="card-content has-text-centered">
                                        <div class="mb-3">
                                            <figure class="image is-96x96 is-inline-block">
                                                <img class="is-rounded" id="bot-card-avatar" src="ganymede-logo.png" alt="Bot Avatar" referrerpolicy="no-referrer" style="background: #f5f5f5;">
                                            </figure>
                                        </div>
                                        <p class="title is-4 cinzel mb-1" id="bot-card-name">Loading Bot...</p>
                                        <p class="subtitle is-6 has-text-grey" id="bot-card-id">--</p>
                                        
                                        <div class="mt-4 pt-4" style="border-top: 1px solid #eee;">
                                            <div class="is-flex is-justify-content-space-between mb-2">
                                                <span class="has-text-grey is-size-7">Platform</span>
                                                <span class="tag is-info is-light is-small" id="bot-card-platform">Discord</span>
                                            </div>
                                        </div>
                                        <div class="mt-3">
                                            <button class="button is-info is-small is-fullwidth is-outlined">
                                                <span class="icon is-small"><i class="fas fa-cog"></i></span>
                                                <span>Configuration & Details</span>
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>"""

replacement = """                        <div class="columns is-multiline" id="bots-list">
                            <!-- Populated dynamically by app.js -->
                        </div>"""

if target in content:
    content = content.replace(target, replacement)
    with open('/Users/mcdoolz/dev/ganymede/src/ganymede/web/themes/default/index.html', 'w') as f:
        f.write(content)
    print("Cleaned index.html")
else:
    print("Target not found")

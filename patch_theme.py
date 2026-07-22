import re
import os

def patch_file(filepath):
    if not os.path.exists(filepath):
        return
        
    with open(filepath, 'r') as f:
        content = f.read()
        
    # 1. Add theme.css right after style.css
    if 'theme.css' not in content:
        content = content.replace('<link rel="stylesheet" href="style.css">', 
                                 '<link rel="stylesheet" href="style.css">\n    <link rel="stylesheet" href="theme.css">')
                                 
    # 2. Remove inline background colors that hardcode styles
    content = re.sub(r'style="z-index: 100; min-height: 2\.5rem; background-color: var\(--header-gold, #926315\);"', 
                     'style="z-index: 100; min-height: 2.5rem; background-color: var(--header-gold, var(--accent-gold));"', content)
                     
    with open(filepath, 'w') as f:
        f.write(content)

patch_file('/Users/mcdoolz/dev/ganymede/src/ganymede/web/index.html')
if os.path.exists(os.path.expanduser('~/.ganymede/web/index.html')):
    patch_file(os.path.expanduser('~/.ganymede/web/index.html'))

theme_path_src = '/Users/mcdoolz/dev/ganymede/src/ganymede/web/theme.css'
theme_path_usr = os.path.expanduser('~/.ganymede/web/theme.css')

theme_content = """/* 
 * Ganymede Custom Theme 
 * Override CSS variables here to customize the aesthetic.
 */
:root {
    /* --bg-alabaster: #f9f9fa; */
    /* --text-obsidian: #111827; */
    /* --text-slate: #4b5563; */
    /* --accent-azure: #0ea5e9; */
    /* --accent-gold: #d97706; */
    /* --border-marble: #e5e7eb; */
    /* --header-gold: #926315; */
}
"""

if not os.path.exists(theme_path_src):
    with open(theme_path_src, 'w') as f:
        f.write(theme_content)

if os.path.exists(os.path.expanduser('~/.ganymede/web')):
    if not os.path.exists(theme_path_usr):
        with open(theme_path_usr, 'w') as f:
            f.write(theme_content)

print("Theming support injected")

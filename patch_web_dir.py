import re
import os

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'r') as f:
    content = f.read()

target = """        # Static Dashboard Routes
        self.web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web')
        if not os.path.exists(self.web_dir):
            os.makedirs(self.web_dir, exist_ok=True)
            
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_static('/', self.web_dir, name='static')"""

replacement = """        # Static Dashboard Routes
        import shutil
        embedded_web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web')
        user_web_dir = os.path.expanduser('~/.ganymede/web')
        
        # If the user directory doesn't exist, or is missing index.html, we copy the embedded one over.
        # This isolates the UI assets from the binary allowing easy theming and overriding.
        if not os.path.exists(user_web_dir) or not os.path.exists(os.path.join(user_web_dir, 'index.html')):
            logger.info("Initializing user web directory with default assets", dest=user_web_dir)
            os.makedirs(user_web_dir, exist_ok=True)
            if os.path.exists(embedded_web_dir):
                shutil.copytree(embedded_web_dir, user_web_dir, dirs_exist_ok=True)
                
        self.web_dir = user_web_dir
            
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_static('/', self.web_dir, name='static')"""

if target in content:
    content = content.replace(target, replacement)
    with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'w') as f:
        f.write(content)
    print("Patched web directory logic")
else:
    print("Target not found")

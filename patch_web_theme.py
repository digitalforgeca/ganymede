
with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'r') as f:
    content = f.read()

target = """        # Static Dashboard Routes
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

replacement = """        # Static Dashboard Routes
        import shutil
        embedded_web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web')
        user_web_dir = os.path.expanduser('~/.ganymede/web')
        
        active_theme = getattr(self.config, "theme", "default")
        
        # If the user directory doesn't exist, we copy the embedded one over to populate themes/default.
        if not os.path.exists(user_web_dir) or not os.path.exists(os.path.join(user_web_dir, 'themes', 'default')):
            logger.info("Initializing user web directory with default assets", dest=user_web_dir)
            os.makedirs(user_web_dir, exist_ok=True)
            if os.path.exists(embedded_web_dir):
                shutil.copytree(embedded_web_dir, user_web_dir, dirs_exist_ok=True)
                
        # Resolve the active theme directory
        theme_dir = os.path.join(user_web_dir, 'themes', active_theme)
        if not os.path.exists(theme_dir):
            logger.warning(f"Theme '{active_theme}' not found, falling back to 'default'")
            theme_dir = os.path.join(user_web_dir, 'themes', 'default')
                
        self.web_dir = theme_dir
            
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_static('/', self.web_dir, name='static')"""

if target in content:
    content = content.replace(target, replacement)
    with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'w') as f:
        f.write(content)
    print("Patched web.py for themes")
else:
    print("Target not found")

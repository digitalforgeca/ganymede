import os

with open('src/ganymede/web/themes/default/index.html', 'w') as f:
    f.write("""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/x-icon" href="/favicon-dark.ico" media="(prefers-color-scheme: light)" />
    <link rel="icon" type="image/x-icon" href="/favicon-light.ico" media="(prefers-color-scheme: dark)" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Ganymede</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@1.0.0/css/bulma.min.css">
    <link rel="stylesheet" href="/style.css">
    <link rel="stylesheet" href="/theme.css">
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""")


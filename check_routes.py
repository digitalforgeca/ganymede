import ast
import glob

for file in glob.glob('/Users/mcdoolz/dev/ganymede/src/ganymede/core/routes/*.py'):
    with open(file, 'r') as f:
        tree = ast.parse(f.read(), filename=file)
    print(f"File: {file} parsed successfully")

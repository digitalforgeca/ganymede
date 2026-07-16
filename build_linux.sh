#!/bin/bash
docker run --rm -v "$(pwd):/src" python:3.11 /bin/bash -c "
cd /src && \
pip install pyinstaller && \
pip install -e . && \
pyinstaller ganymede.spec --workpath /tmp/build --distpath /src/dist/linux
"

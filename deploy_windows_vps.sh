#!/bin/bash
set -e
echo "1. Syncing source to VPS..."
rsync -avz --exclude '.venv' --exclude '.git' --exclude 'build' --exclude 'dist' --exclude '__pycache__' ./ forge:/tmp/ganymede-win-build/

echo "2. Running remote build..."
ssh forge << 'EOF'
set -e
cd /tmp/ganymede-win-build
cat << 'DOCKERFILE' > Dockerfile.windows
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN dpkg --add-architecture i386 && \
    apt-get update && apt-get install -y --no-install-recommends \
    wine wine64 wine32 wget ca-certificates xvfb winbind unzip && \
    rm -rf /var/lib/apt/lists/*

ENV WINEARCH=win64
ENV WINEPREFIX=/wine

# Set Wine to Windows 10 mode (required for Python 3.11 and bcryptprimitives.dll)
RUN xvfb-run -a winecfg -v win10 && wineserver -w

# Install Python 3.11.9 for Windows
RUN wget -qO /tmp/python.zip https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip && \
    mkdir -p "/wine/drive_c/Program Files/Python311" && \
    cd "/wine/drive_c/Program Files/Python311" && \
    unzip /tmp/python.zip && \
    rm /tmp/python.zip && \
    sed -i 's/#import site/import site/g' python311._pth && \
    wget -qO get-pip.py https://bootstrap.pypa.io/get-pip.py && \
    xvfb-run -a wine python.exe get-pip.py

WORKDIR /src
COPY . /src

# Upgrade PIP and install dependencies via Wine Python
RUN xvfb-run -a wine "C:/Program Files/Python311/python.exe" -m pip install --upgrade pip && \
    xvfb-run -a wine "C:/Program Files/Python311/python.exe" -m pip install hatchling pyinstaller && \
    xvfb-run -a wine "C:/Program Files/Python311/python.exe" -m pip install .

# Run Pyinstaller to compile the executable
RUN xvfb-run -a wine "C:/Program Files/Python311/Scripts/pyinstaller.exe" ganymede.spec --workpath /tmp/build --distpath /src/dist/windows
DOCKERFILE

echo "Building Docker image..."
docker build -t ganymede-win-builder -f Dockerfile.windows .
echo "Extracting binary..."
docker rm -f extract || true
docker create --name extract ganymede-win-builder
docker cp extract:/src/dist/windows ./dist/
docker rm -f extract
EOF

echo "3. Pulling artifact back to Mac..."
mkdir -p dist/windows
rsync -avz forge:/tmp/ganymede-win-build/dist/windows/ ./dist/windows/
echo "Deploy pipeline complete! Binary should be in dist/windows/"

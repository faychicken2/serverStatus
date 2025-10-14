# From your project folder (has devbox_watcher.py)
# Create a quick requirements.txt (or edit to match yours)
printf "pystray\nPillow\n" > requirements.txt

# Run a Windows-targeting PyInstaller inside Docker
docker run --rm -v "$PWD":/src -w /src \
  cdrx/pyinstaller-windows:python3 \
  bash -lc "pip install -r requirements.txt && \
            pyinstaller --onefile --windowed --name DevboxWatcher devbox_watcher.py"

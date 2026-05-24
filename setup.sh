#!/bin/bash
# SubtitleForge — Setup Script
# Instala todas las dependencias necesarias

set -e

echo "🎬 SubtitleForge — Instalación"
echo "═══════════════════════════════════════"

# 1. System dependencies
echo ""
echo "📦 Instalando dependencias del sistema..."
if command -v apt &> /dev/null; then
    sudo apt update && sudo apt install -y ffmpeg
elif command -v pacman &> /dev/null; then
    sudo pacman -S --noconfirm ffmpeg
elif command -v dnf &> /dev/null; then
    sudo dnf install -y ffmpeg
else
    echo "⚠️  No se pudo detectar el gestor de paquetes. Instala ffmpeg manualmente."
fi

# 2. Python virtual environment
echo ""
echo "🐍 Creando entorno virtual..."
if command -v python3.12 &> /dev/null; then
    PYTHON_BIN=python3.12
else
    PYTHON_BIN=python3
fi

PYTHON_VERSION=$($PYTHON_BIN - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)

if ! $PYTHON_BIN - <<'PY'
import sys
raise SystemExit(0 if sys.version_info < (3, 13) else 1)
PY
then
    echo "❌ Python $PYTHON_VERSION no es compatible con PaddleOCR/PaddlePaddle todavía."
    echo "   Instala Python 3.12 y vuelve a ejecutar ./setup.sh"
    exit 1
fi

$PYTHON_BIN -m venv --clear venv
source venv/bin/activate

# 3. Python dependencies
echo ""
echo "📥 Instalando dependencias Python..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Create directories
echo ""
echo "📁 Creando directorios..."
mkdir -p uploads output temp

# 5. LibreTranslate (optional)
echo ""
echo "═══════════════════════════════════════"
echo "✅ Instalación completada!"
echo ""
echo "Para iniciar el servidor:"
echo "  source venv/bin/activate"
echo "  python server.py"
echo ""
echo "Para traducción (opcional, en otra terminal):"
echo "  pip install libretranslate"
echo "  libretranslate --host 0.0.0.0 --port 5000"
echo ""
echo "Abre en el navegador: http://localhost:8000"
echo "═══════════════════════════════════════"

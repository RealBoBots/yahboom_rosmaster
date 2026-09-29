#!/usr/bin/env bash
# Puesta a punto del workspace del Challenge JAR 2026 en Ubuntu 22.04 nativo.
#
# No instala nada ni usa sudo: verifica el entorno, arma el workspace y
# compila. Lo que falte se reporta con el comando de instalacion para que lo
# corras vos, porque instalar ROS o drivers es una decision tuya, no del script.
#
# Es idempotente: se puede correr las veces que haga falta.
set -uo pipefail

WS="${JAR_WS:-$HOME/rosmaster_ws}"
FORK_URL="https://github.com/AIRclub-UdeSA/yahboom_rosmaster.git"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ok(){ printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad(){ printf '  \033[31mFALTA\033[0m %s\n' "$1"; FALTAN=1; }
warn(){ printf '  \033[33mAVISO\033[0m %s\n' "$1"; }
head(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

FALTAN=0

head "1. Plataforma"
if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  warn "Esto es WSL. El script sirve igual, pero el objetivo era Ubuntu nativo:"
  warn "en WSL vas a seguir con render por software y sensores lentos."
else
  ok "Linux nativo ($(. /etc/os-release && echo "$PRETTY_NAME"))"
fi

head "2. Aceleracion grafica"
if command -v glxinfo >/dev/null 2>&1; then
  REND=$(glxinfo -B 2>/dev/null | grep -m1 'OpenGL renderer' | cut -d: -f2- | sed 's/^ //')
  GLVER=$(glxinfo -B 2>/dev/null | grep -m1 'OpenGL core profile version' | cut -d: -f2- | sed 's/^ //')
  case "$REND" in
    *llvmpipe*|*softpipe*|*swrast*)
      bad "renderer '$REND' es por software. Instala el driver de la GPU." ;;
    *D3D12*)
      bad "renderer '$REND': seguis sobre la traduccion de WSL, no hay GPU real." ;;
    "")
      bad "glxinfo no devolvio renderer. Hay servidor grafico corriendo?" ;;
    *)
      ok "renderer: $REND"
      ok "OpenGL: ${GLVER:-desconocido}" ;;
  esac
else
  bad "glxinfo  ->  sudo apt install -y mesa-utils"
fi

head "3. Dependencias"
[ -f /opt/ros/humble/setup.bash ] && ok "ROS 2 Humble" \
  || bad "ROS 2 Humble  ->  https://docs.ros.org/en/humble/Installation.html"
command -v ign >/dev/null 2>&1 && ok "Gazebo Fortress ($(ign gazebo --versions 2>/dev/null | head -1))" \
  || bad "Gazebo Fortress  ->  sudo apt install -y ignition-fortress"
command -v colcon >/dev/null 2>&1 && ok "colcon" \
  || bad "colcon  ->  sudo apt install -y python3-colcon-common-extensions"
command -v git >/dev/null 2>&1 && ok "git" || bad "git  ->  sudo apt install -y git"
command -v xterm >/dev/null 2>&1 && ok "xterm (para el teleop)" \
  || bad "xterm  ->  sudo apt install -y xterm"
python3 -c 'import yaml' 2>/dev/null && ok "python3-yaml" \
  || bad "python3-yaml  ->  sudo apt install -y python3-yaml"
for P in ros-humble-ros-gz ros-humble-gz-ros2-control ros-humble-topic-tools \
         ros-humble-teleop-twist-keyboard; do
  dpkg -l "$P" >/dev/null 2>&1 && ok "$P" || bad "$P  ->  sudo apt install -y $P"
done

if [ "$FALTAN" -ne 0 ]; then
  printf '\n\033[31mFaltan dependencias.\033[0m Instalalas y volve a correr el script.\n'
  exit 1
fi

head "4. Workspace en $WS"
mkdir -p "$WS/src"
if [ -d "$WS/src/yahboom_rosmaster/.git" ]; then
  ok "fork ya clonado ($(git -C "$WS/src/yahboom_rosmaster" log -1 --format=%h))"
else
  echo "  clonando el fork del club..."
  git clone --depth 1 "$FORK_URL" "$WS/src/yahboom_rosmaster" || {
    printf '\n\033[31mNo se pudo clonar.\033[0m Si el repo es privado, configura tus\n'
    printf 'credenciales de GitHub en esta maquina y volve a correr el script.\n'; exit 1; }
  ok "fork clonado"
fi

PKG_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ "$PKG_SRC" != "$WS/src/jar_bringup" ]; then
  echo "  copiando jar_bringup desde $PKG_SRC"
  mkdir -p "$WS/src/jar_bringup"
  cp -r "$PKG_SRC"/. "$WS/src/jar_bringup"/
fi
ok "jar_bringup en $WS/src/jar_bringup"

head "5. Compilando"
# shellcheck disable=SC1091
. /opt/ros/humble/setup.bash
( cd "$WS" && colcon build --symlink-install ) || {
  printf '\n\033[31mFallo la compilacion.\033[0m Revisa la salida de arriba.\n'; exit 1; }
ok "compilado"

head "Listo. Proximos pasos"
cat <<EOF

  source $WS/install/setup.bash

  Laberinto con sensores (en Ubuntu nativo los defaults ya son correctos:
  ogre2 sobre GPU, sin render por software):

    ros2 launch jar_bringup sim.launch.py world:=maze_1_6x5_victimas

  En el log NO tiene que aparecer la advertencia sobre sensores de render.

  Verifica que el LiDAR realmente mida:

    ros2 topic echo /scan --once --qos-reliability best_effort

  Si los 'ranges' varian entre ~0.4 y varios metros, esta todo bien.
  Si son todos 0.05, el motor de render no es el correcto.

  Validacion de movimiento (cerra el teleop antes, se pisan en /cmd_vel):

    ros2 run jar_bringup drive_check

  Teleop, en otra terminal:

    ros2 launch jar_bringup teleop.launch.py

EOF

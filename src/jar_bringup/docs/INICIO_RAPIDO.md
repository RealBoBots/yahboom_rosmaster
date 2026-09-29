# Inicio rápido

Todo ROS corre **adentro del contenedor**. Los archivos se editan desde el host.

## 1. Contenedor y compilación

En el host:

```bash
cd ~/rosmaster_ws/src/yahboom_rosmaster/dockerfiles && ./container.sh start
```

Sólo si estás por SSH y querés ver Gazebo/RViz (antes de entrar):

```bash
export DISPLAY=:0 XAUTHORITY=$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* | head -1)
```

```bash
./container.sh enter
```

Adentro:

```bash
cd ~/rosmaster_ws && colcon build --symlink-install && source install/setup.bash
```

Tienen que terminar 11 paquetes. Si algo queda raro, compilá desde cero
agregando `rm -rf build install log &&` al principio.

## 2. Simulación (terminal 1, adentro)

```bash
ros2 launch jar_bringup sim.launch.py world:=maze_1_6x5_victimas
```

RViz: robot con colores y cámara con imagen. Por SSH, mirá la pantalla por RDP.

## 3. Prueba (terminal 2)

```bash
~/rosmaster_ws/src/yahboom_rosmaster/dockerfiles/container.sh enter
```

```bash
ros2 run jar_bringup drive_check
```

Tiene que decir `RESULT: PASS`.

## 4. Manejar a mano (opcional, necesita pantalla)

```bash
ros2 launch jar_bringup teleop.launch.py
```

`w/s` adelante/atrás · `a/d` costado · `j/l` girar · espacio frena.
Cerralo antes de volver a usar `drive_check`.

## 5. Apagar

Ctrl+C en cada terminal, `exit`, y en el host `./container.sh stop`.

## Si falla

| síntoma | solución |
|---|---|
| robot blanco en RViz | RViz tiene que correr adentro del contenedor |
| `could not connect to display` | falta el `export DISPLAY...` del paso 1 |
| `drive_check` dice que hay otro publicador | cerrá el teleop |
| tópicos sin datos | cerrá todo y `rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*` |

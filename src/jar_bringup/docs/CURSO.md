# Cómo correr el curso oficial del Challenge JAR en este workspace

Guía práctica para hacer los 9 workshops de
[`jar_workshops`](https://github.com/AIRclub-UdeSA/jar_workshops) en esta
máquina (Ubuntu 22.04 nativo). La teoría de cada semana está en el sitio:
https://airclub-udesa.github.io/jar_site/workshops/

Esta guía no reemplaza al sitio. Junta los comandos en un solo lugar y marca
los ajustes que hacen falta acá.

## 0. Preparación (una sola vez)

**Todo se compila y se corre adentro del contenedor Docker del fork.** Los
comandos `ros2 ...` y `colcon ...` de esta guía van **adentro** del
contenedor, nunca en el host. Los archivos se editan desde el host (VS Code),
porque el contenedor monta `~/rosmaster_ws`.

1. Los workshops vienen como **submódulo del fork** (`RealBoBots/jar_workshops`),
   en `~/rosmaster_ws/src/yahboom_rosmaster/src/jar_workshops`. Para
   traerlos o actualizarlos (en el host):

   ```bash
   cd ~/rosmaster_ws/src/yahboom_rosmaster && git pull && git submodule update --init
   ```

2. Levantá el contenedor y compilá todo. La primera vez construye la imagen.
   Ojo: el `Dockerfile` de RealBoBots no trae Nav2, OpenCV/cv_bridge, SciPy
   ni xterm; si la imagen se reconstruye, faltan para las semanas 04 a 09.

   ```bash
   cd ~/rosmaster_ws/src/yahboom_rosmaster/dockerfiles && ./container.sh start && ./container.sh build
   ```

3. Para cada terminal que diga la guía, abrí una shell adentro:

   ```bash
   ~/rosmaster_ws/src/yahboom_rosmaster/dockerfiles/container.sh enter
   ```

   Esa shell ya tiene ROS y el workspace cargados.

Para ver Gazebo, RViz o la ventana del teleop, abrí las terminales desde la
sesión gráfica de la notebook o por RDP. Por SSH no hay pantalla: usá
`headless:=true rviz:=false`.

Reglas generales:

- **Nunca** corras `colcon build` en el host: rompe el `install/` del contenedor.
- Si una shell de adentro no encuentra un paquete recién compilado, corré `source install/setup.bash`.
- **Los workshops vienen incompletos a propósito.** Cada archivo tiene
  funciones marcadas con `TODO` que completás vos. Si corrés un nodo sin
  completarlo, no hace nada o falla.
- Con `--symlink-install`, los cambios en `.py` no necesitan recompilar.
  Sí hay que recompilar cuando agregás archivos o entry points nuevos.
- **Un solo publicador en `/cmd_vel` por vez.** No corras el teleop junto con
  un nodo que maneje el robot: se pisan.
- Cerrá siempre con **Ctrl+C**, nunca con `kill -9`.

### Simulador: el del curso o el de `jar_bringup`

El curso levanta la simulación con

```bash
ros2 launch yahboom_rosmaster_bringup rosmaster_x3_sim.launch.py world:=... motion_profile:=ideal
```

En esta máquina conviene usar el equivalente de `jar_bringup`, con los mismos
argumentos:

```bash
ros2 launch jar_bringup sim.launch.py world:=... motion_profile:=ideal
```

Hacen lo mismo, pero el de `jar_bringup` trae un RViz donde **la cámara se
ve** (en el del fork queda en negro por un problema de QoS). Los dos sirven
para el curso.

El teleop del curso es `ros2 run teleop_twist_keyboard teleop_twist_keyboard`.
Acá conviene `ros2 launch jar_bringup teleop.launch.py`, que maneja de forma
continua y sin tirones. Teclas: `w/s` adelante y atrás, `a/d` lateral,
`q/e` diagonales, `j/l` giro, espacio para frenar.

## Semanas 01 y 02: primeros pasos

### 01 · Talkers y listeners

Completá `talker.py` y `listener.py` en
`semana-01-talkers-listeners/talkers_listeners/talkers_listeners/`.

```bash
cd ~/rosmaster_ws && colcon build --symlink-install --packages-select talkers_listeners && source install/setup.bash
```

En otra terminal:

```bash
ros2 run talkers_listeners talker
```

En una tercera terminal:

```bash
ros2 run talkers_listeners listener
```

Para verificar: `ros2 topic echo /mensaje`.

### 02 · Zigzag mecanum

Simulación:

```bash
ros2 launch jar_bringup sim.launch.py
```

Compilá:

```bash
cd ~/rosmaster_ws && colcon build --symlink-install --packages-select zigzag_mecanum && source install/setup.bash
```

Corré el nodo:

```bash
ros2 run zigzag_mecanum zigzag
```

## Semanas 03 a 05: sensores

### 03 · Evasión de obstáculos

```bash
ros2 launch jar_bringup sim.launch.py world:=cafe motion_profile:=ideal
```

```bash
cd ~/rosmaster_ws && colcon build --symlink-install --packages-select evasion_obstaculos && source install/setup.bash
```

```bash
ros2 run evasion_obstaculos evasor --ros-args -p angulo_vision_deg:=90.0 -p distancia_choque_m:=0.6 -p angulo_giro_deg:=110.0
```

Debug: `ros2 topic hz /scan_cono`. Ese tópico sólo aparece cuando
`hay_obstaculo()` está completa.

### 04 · Detección de color

```bash
ros2 launch jar_bringup sim.launch.py world:=laberinto_simple_victimas motion_profile:=ideal
```

```bash
cd ~/rosmaster_ws && colcon build --symlink-install --packages-select deteccion_color && source install/setup.bash
```

Parte 1, sólo la cámara:

```bash
ros2 run deteccion_color detector
```

Parte 2, cámara más LiDAR:

```bash
ros2 run deteccion_color detector_scan
```

Teleop en otra terminal, para acercar el robot a los cubos:

```bash
ros2 launch jar_bringup teleop.launch.py
```

Verificá con `ros2 topic echo /rojo_detectado` (parte 1) y
`ros2 topic echo /scan_rojo` (parte 2).

### 05 · Launch files y RViz

```bash
cd ~/rosmaster_ws && colcon build --symlink-install --packages-select launch_rviz && source install/setup.bash
```

Estos launch **ya levantan la simulación**, así que no abras otra antes.
El de la semana 03:

```bash
ros2 launch launch_rviz evasion.launch.py
```

El de la semana 04:

```bash
ros2 launch launch_rviz deteccion_color.launch.py
```

Guardá tu configuración de RViz: la vas a reusar desde la semana 06.

## Semanas 06 a 08: navegación con mapa

Acá **no hay paquete armado**. Cada semana creás el tuyo, copiás los `.py` de
la carpeta de la semana y registrás cada nodo en `entry_points` de
`setup.py`. El README de la semana 06 explica el procedimiento completo.

Las tres semanas usan `laberinto_simple`, el único mundo que trae mapa
(`maps/laberinto_simple.yaml`).

### 06 · Localización

Creá el paquete:

```bash
cd ~/rosmaster_ws/src/yahboom_rosmaster/src/jar_workshops/semana-06-localizacion && ros2 pkg create --build-type ament_python --dependencies rclpy nav_msgs sensor_msgs geometry_msgs tf2_ros localizacion
```

Copiá `localizador.py` y `campo_verosimilitud.py` adentro del paquete,
registralos en `setup.py`, completá los `TODO` y compilá:

```bash
cd ~/rosmaster_ws && colcon build --symlink-install --packages-select localizacion && source install/setup.bash
```

Para correrlo, una terminal por paso:

1. Simulación:

   ```bash
   ros2 launch jar_bringup sim.launch.py world:=laberinto_simple motion_profile:=ideal rviz:=false
   ```

2. Servidor del mapa:

   ```bash
   ros2 run nav2_map_server map_server --ros-args -p yaml_filename:="$(ros2 pkg prefix yahboom_rosmaster_gazebo)/share/yahboom_rosmaster_gazebo/maps/laberinto_simple.yaml"
   ```

3. Activar el mapa:

   ```bash
   ros2 run nav2_lifecycle_manager lifecycle_manager --ros-args -p autostart:=true -p node_names:="['map_server']"
   ```

4. Tus nodos:

   ```bash
   ros2 run localizacion campo_verosimilitud & ros2 run localizacion localizador
   ```

5. Teleop:

   ```bash
   ros2 launch jar_bringup teleop.launch.py
   ```

6. RViz con tu configuración de la semana 05:

   ```bash
   rviz2 -d <ruta a tu .rviz>
   ```

### 07 · Obstáculos fuera del mapa

Creá el paquete `obstaculos_no_mapeados` y copiá `detector_obstaculos.py`.
Corré todo lo de la semana 06, pero con
`world:=laberinto_simple_victimas` y **el mismo mapa**, y sumá tu nodo
`detector_obstaculos`. Los cubos no están en el mapa: son justo lo que el
nodo tiene que encontrar.

Resultado: `/objetos_no_mapeados` (PoseArray) y
`/objetos_no_mapeados_markers` (para RViz).

### 08 · Cobertura del mapa

Creá el paquete `cobertura_mapa` y copiá `trazado.py`, `planificador.py`,
`grilla_cobertura.py` y `explorador.py`. Además, sumale a tu `localizador.py`
de la semana 06 el método `recibir_pose_inicial`, que viene resuelto en el
README de la semana 08.

Corré lo mismo que en la semana 06, más `grilla_cobertura` y `explorador`.
En RViz agregá la herramienta **"2D Pose Estimate"** y marcá dónde está el
robot: espera unos 3 s y arranca a explorar solo.

SciPy (`distance_transform_edt`) ya está instalado en esta máquina.

## Semana 09: Nav2

No hace falta compilar. Un solo comando levanta todo (simulación, AMCL,
costmaps, planner, controller y RViz):

```bash
ros2 launch ~/rosmaster_ws/src/yahboom_rosmaster/src/jar_workshops/semana-09-nav2/launch/nav2_semana09.launch.py
```

En RViz: primero **"2D Pose Estimate"** para ubicar el robot, después
**"Nav2 Goal"** para mandarlo a un destino.

## Si algo falla

| síntoma | causa probable | solución |
|---|---|---|
| el nodo no recibe `/scan` ni la cámara, y no hay error | suscripción Reliable contra un publicador Best Effort | usar `qos_profile_sensor_data` |
| el robot "ve" obstáculos atrás cuando están adelante | el 0° del LiDAR apunta hacia atrás | el frente es el ángulo 180°, o transformar con tf2 |
| el robot se mueve a los tirones o no hace caso | dos publicadores en `/cmd_vel` | cerrá el teleop |
| tópicos que existen pero no tienen datos, o segfault de Gazebo al arrancar | quedó memoria compartida de una corrida matada | cerrar todo y `rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*` |
| `/odom` o el TF `odom` no aparecen | el fork los levanta a los ~12 s | esperar |
| `package not found` en `nav2_*` | Nav2 no instalado | paso 0 |
| dudás de que la simulación esté sana | — | `ros2 run jar_bringup drive_check` (con el teleop cerrado) |

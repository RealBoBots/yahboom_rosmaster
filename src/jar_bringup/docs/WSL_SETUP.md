# Poner a correr la simulación del ROSMASTER X3 en WSL2

Guía de puesta a punto para el Challenge JAR 2026 — AIR Club UdeSA.

Sirve para reproducir el entorno desde cero en una máquina WSL2 nueva. Cada
paso dice **por qué** existe, porque varios corrigen problemas que no son
evidentes y que vuelven si alguien "limpia" la configuración sin saber.

**Regla de oro:** `src/yahboom_rosmaster` es un fork del club y es de solo
lectura. Todo lo de acá vive en `jar_bringup` o en configuración del host.

## Entorno de referencia

| | |
|---|---|
| Host | Windows + WSL2, Ubuntu 22.04 (jammy) |
| GPU | NVIDIA Quadro M1000M vía WSLg |
| Driver gráfico | Mesa D3D12, OpenGL 4.2 |
| ROS | ROS 2 Humble |
| Simulador | Gazebo Fortress (`ign gazebo` 6.18) |

---

# Parte 1 — El reloj del sistema

**Hacé esto primero.** Si el reloj está inestable, todo lo demás va a fallar de
formas confusas y vas a perder horas persiguiendo síntomas equivocados.

## El problema

ROS 2 corre sus timers sobre `RCL_SYSTEM_TIME`, que es `CLOCK_REALTIME`. En
WSL2 ese reloj puede quedar en manos de dos sincronizadores que se pisan: el
**TimeSync de Hyper-V** (driver `hv_utils`, que copia la hora del host Windows)
y algún demonio NTP del invitado (`systemd-timesyncd`).

Cuando pelean, el reloj salta hacia adelante y hacia atrás varias veces por
segundo. En esta máquina eran **±87 segundos**.

### Cómo se manifiesta

No se manifiesta como "el reloj está mal". Se manifiesta como:

| Síntoma | Medido acá |
|---|---|
| Timer `rclpy` de 20 Hz | dispara a 2.6–3.5 Hz |
| `ros2 topic pub -r 20` | publica a 7.6 Hz |
| `cmd_vel_watchdog` del fork (30 Hz) | publica a 1.8–2.0 Hz |
| `ros2 topic hz` | reporta huecos de 87 s e intervalos negativos |
| RViz | `Message Filter dropping message: the timestamp on the message is earlier than all the data in the transform cache` |
| Manejo del robot | responde tarde y a los tirones |

El robot se mueve a los tirones porque el watchdog reemite a 2 Hz contra su
propio timeout de 0.5 s, y MecanumDrive mantiene el último comando hasta que
llega el siguiente.

## Diagnóstico

```bash
python3 -c "
import time
p=time.clock_gettime(time.CLOCK_REALTIME); w=0.0; t0=time.monotonic()
while time.monotonic()-t0 < 3:
    c=time.clock_gettime(time.CLOCK_REALTIME); w=min(w,c-p); p=c
print('max backward step:', w)"
```

- `0.0` → reloj sano, seguí a la Parte 2.
- Un número negativo grande → tenés el problema.

Contrastá con `CLOCK_MONOTONIC`, que no lo sufre: si MONOTONIC está limpio y
REALTIME salta, es un escritor pisando el reloj, no hardware roto.

## Solución

### Paso 1 — Apagar el NTP del invitado

```bash
sudo systemctl disable --now systemd-timesyncd
```

En esta máquina **esto solo no alcanzó**. Es la mitad del arreglo.

### Paso 2 — Desvincular el TimeSync de Hyper-V

Buscá el GUID del dispositivo TimeSync. Es distinto en cada máquina, así que
identificalo por su `class_id`, que sí es fijo:

```bash
for d in /sys/bus/vmbus/devices/*/; do
  grep -q '9527e630-d0ae-497b-adce-e80ab0175caf' "$d/class_id" 2>/dev/null \
    && echo "TimeSync: $(basename $d)"
done
```

Desvinculalo (reemplazá el GUID por el tuyo):

```bash
echo <GUID> | sudo tee /sys/bus/vmbus/drivers/hv_utils/unbind
```

El driver es `hv_utils`, **con S**. Verificá que ese dispositivo sea el único
vinculado a `hv_utils` antes de desvincularlo, para no apagar de paso otro
servicio de integración:

```bash
ls /sys/bus/vmbus/drivers/hv_utils/
```

### Paso 3 — Verificar

```bash
python3 -c "
import time
p=time.clock_gettime(time.CLOCK_REALTIME); w=0.0; t0=time.monotonic()
while time.monotonic()-t0 < 10:
    c=time.clock_gettime(time.CLOCK_REALTIME); w=min(w,c-p); p=c
print('max backward step:', w)"
```

Tiene que dar `0.0`. Acá dio `0.0` en una ventana de 10 s tras el desvinculado.

### Paso 4 — Hacerlo persistente

El desvinculado **se pierde al reiniciar WSL**. Una vez confirmado:

```bash
sudo tee /etc/systemd/system/disable-hv-timesync.service >/dev/null <<'EOF'
[Unit]
Description=Unbind the Hyper-V TimeSync device so it stops stepping CLOCK_REALTIME
After=systemd-remount-fs.service
Before=systemd-timesyncd.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'echo <GUID> > /sys/bus/vmbus/drivers/hv_utils/unbind'

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable disable-hv-timesync.service
```

## Cuidado: todas las distros WSL2 comparten un solo reloj

WSL2 corre **un único kernel** para todas las distros. `wsl -l -v` en esta
máquina muestra tres corriendo:

```
  NAME              STATE           VERSION
* Ubuntu-24.04      Running         2
  docker-desktop    Running         2
  Ubuntu-22.04      Running         2
```

Consecuencias prácticas:

- El desvinculado de `hv_utils` toca el kernel, así que vale **para todas** las
  distros. Se hace una sola vez, desde cualquiera.
- `systemd-timesyncd` en cambio corre **por distro**. Si lo dejás activo en más
  de una, vuelven a pelear por el mismo `CLOCK_REALTIME`. En esta máquina
  alcanzó con reactivarlo en Ubuntu-22.04 para que el reloj se rompiera otra
  vez, así que **alguna de las otras dos distros también lo escribe**.
- Si el reloj vuelve a saltar sin razón aparente, revisá si arrancó un demonio
  NTP en otra distro (`docker-desktop` es sospechoso habitual).

### Cómo identificar la distro culpable

Si `hv_utils` está desvinculado y `timesyncd` inactivo en esta distro pero el
reloj **igual** salta, el escritor está en otra. Apagalas de a una desde
PowerShell y volvé a medir después de cada una — es reversible, `wsl -t` solo
termina la distro:

```
wsl -t docker-desktop
wsl -t Ubuntu-24.04
```

Cuando la medición dé `0.0`, la última que apagaste es la culpable. Después
podés volver a levantarla con su `systemd-timesyncd` desactivado:

```
wsl -d Ubuntu-24.04 -- sudo systemctl disable --now systemd-timesyncd
```

## Sobre el atraso residual

Tras el arreglo el reloj queda **estable pero libre**: acá quedó 516 s atrasado
y deriva lentamente (~25 s/hora), porque ya no lo disciplina nadie.

**Para simulación eso está bien.** ROS necesita un reloj *estable*; que sea
exacto no le importa. Un reloj exacto que salta es mucho peor que uno estable
corrido.

### No reactives `systemd-timesyncd`

Probado en esta máquina, con `hv_utils` ya desvinculado:

| estado | resultado |
|---|---|
| `timesyncd` desactivado | `max backward: 0.0` — estable |
| `timesyncd` reactivado | `max backward: -87.06`, 124 saltos en 5 min |

Vuelve a romperse porque las tres distros comparten el mismo
`CLOCK_REALTIME` y alguna de las otras también lo escribe. Se ve en la propia
medición NTP de `timesyncd`, donde el `ReceiveTimestamp` del servidor queda
87 s **antes** del `OriginateTimestamp` local, con `Jitter=46.5s`:

```
OriginateTimestamp=Sun 2026-09-06 23:01:59 -03
ReceiveTimestamp=Sun 2026-09-06 23:00:32 -03
```

O sea, el reloj se movió durante el propio viaje de ida y vuelta del paquete.

### Si querés corregir el atraso igual

Hacé una corrección **de una sola vez**, que no deja ningún demonio
escribiendo. Nunca con la simulación corriendo:

```bash
sudo date -s "$(python3 -c "
import socket,struct,datetime
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(5)
s.sendto(b'\x1b'+47*b'\0',('pool.ntp.org',123))
d,_=s.recvfrom(1024)
print(datetime.datetime.fromtimestamp(struct.unpack('!12I',d)[10]-2208988370).strftime('%Y-%m-%d %H:%M:%S'))")"
```

Va a volver a atrasarse de a poco. Repetilo cuando moleste.

---

# Parte 2 — El crash de Gazebo

## El problema

Gazebo Fortress aborta en WSLg con:

```
OGRE EXCEPTION(9:UnimplementedException): in GL3PlusTextureGpu::copyTo
```

Ogre-Next 2.2 —el motor `ogre2`, que es el default— genera mipmaps por hardware
con una copia de textura que el driver D3D12 de Mesa no implementa. Ocurre
mientras construye los materiales de la escena, así que mata **el servidor** en
cuanto aparece un sensor de render, y **el cliente GUI** en cuanto dibuja.

`LIBGL_ALWAYS_SOFTWARE=1` lo evita, pero bajando todo a llvmpipe (CPU).

## La solución: OGRE 1.x

El motor `ogre` (OGRE 1.x) nunca toma ese camino y corre en GPU. Es el mismo
motor que usa RViz, que por eso siempre anduvo bien.

### Pero OGRE 1.x deja ciego al robot

**Verificado midiendo `/scan` en el mismo laberinto, con el robot en la misma
posición:**

| motor | lectura del LiDAR |
|---|---|
| `ogre` | los 1080 rayos en 0.05 m, que es `range_min` |
| `ogre2` + llvmpipe | 1080 rayos, min 0.48 m, max 3.63 m — paredes reales |

El robot se mueve libremente, así que no está enterrado en una pared: el sensor
sencillamente no mide. La simulación *parece* sana y el LiDAR está muerto, que
es peor que el crash que reemplazó.

Entonces la elección de motor es entre dos cosas que funcionan, no una:

| necesitás | motor | `software_gl` | costo |
|---|---|---|---|
| movimiento, física, teleop | `ogre` | `false` (GPU) | RTF ~1.0, sin `/scan` usable |
| LiDAR o cámara | `ogre2` | `true` (llvmpipe) | sensores reales, RTF 0.5–0.8 |

`sim.launch.py` avisa al arrancar cuando elegís `ogre`, y el render por
software se lo da **solo al servidor**: la GUI de Gazebo y RViz se quedan en
GPU vía `additional_env`. Forzar RViz a llvmpipe le costaba más de un core
entero y frenaba toda la simulación.

| motor | servidor | cliente GUI | renderer | RTF |
|---|---|---|---|---|
| `ogre2` (default) | aborta | aborta | — | — |
| `ogre2` + `LIBGL_ALWAYS_SOFTWARE=1` | corre | corre | llvmpipe | lento |
| **`ogre`** | corre | corre | **D3D12 (NVIDIA Quadro M1000M)** | 0.94 |

## Por qué hace falta un paquete y no un flag

`ign gazebo` acepta `--render-engine`, pero **el launch del fork no lo expone**:
arma la línea de comando a mano. Y los worlds tienen
`<render_engine>ogre2</render_engine>` hardcodeado. Como el fork es de solo
lectura, `jar_bringup` mete el motor por dos caminos:

- **Servidor** — reescribe solo el elemento `<render_engine>` en una copia
  generada del world (en `/tmp/jar_bringup_worlds/`) y la pasa por el argumento
  `world` que el fork ya expone. Los `model://` siguen resolviendo por
  `IGN_GAZEBO_RESOURCE_PATH`.
- **Cliente GUI** — lanza su propio `ign gazebo -g --render-engine-gui ogre` y
  le pide `gui:=false` al fork, para que corra un solo cliente.

---

# Parte 3 — Compilar

```bash
cd ~/rosmaster_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select jar_bringup --symlink-install
source install/setup.bash
```

`jar_bringup` no requiere recompilar el fork.

---

# Parte 4 — Correr, y la palanca de performance

```bash
ros2 launch jar_bringup sim.launch.py physics_step:=0.002
```

En el log tienen que aparecer estas dos líneas y **ningún** `UnimplementedException`:

```
[INFO] [jar_sim]: Render engine 'ogre': rewrote 1 Sensors system(s) into /tmp/...
[Msg] Loading plugin [ignition-rendering-ogre]
```

Confirmá que está en GPU y no cayó a software:

```bash
grep GL_RENDERER ~/.ignition/rendering/ogre.log | tail -1
```

Tiene que decir `D3D12 (NVIDIA Quadro M1000M)`, no `llvmpipe`.

## Por qué `physics_step`

**RTF** (Real Time Factor) es la relación entre tiempo simulado y tiempo real.
1.0 = velocidad real; 0.58 = cámara lenta.

Medido con robot completo, LiDAR y cámara RGB-D:

| visores | paso de física | RTF |
|---|---|---|
| Gazebo GUI + RViz | 1 ms (el del fork) | 0.58 |
| solo Gazebo GUI | 1 ms | 0.60–0.70 |
| solo RViz | 1 ms | 0.72–0.77 |
| headless | 1 ms | 0.94 |
| headless, sin sensores de render | 1 ms | 0.97 |
| **Gazebo GUI + RViz** | **2 ms** | **0.99** |
| Gazebo GUI + RViz | 4 ms | 1.00 |

El paso de 1 ms fija dos cosas a la vez: la carga de física del servidor **y**
la frecuencia de `/clock`, que a 1 ms sale a ~1 kHz. Cada nodo con
`use_sim_time` paga esos mil callbacks por segundo: `calculated_odometry.py`
del fork se come 70% de un core solo con eso. A 4 ms ese nodo baja a 7%.

**Los sensores de render no son el cuello de botella** — apagarlos compra 0.03
de RTF. No pierdan tiempo ahí.

`physics_step` es **opt-in y por defecto no toca el world**, porque engrosar el
paso cambia la física de contacto y los perfiles de movimiento del fork están
calibrados a 1 ms.

- **2 ms** para desarrollo interactivo: tiempo real con los dos visores.
- **sin setear** para tuning de perfiles, tests de trayectoria y corridas finales.

El world generado lleva el paso en el nombre (`empty.ogre.0.002s.world`), así
que siempre se ve con qué ritmo se produjo un resultado.

## Argumentos útiles

| argumento | default | para qué |
|---|---|---|
| `render_engine` | `ogre` | `ogre2` reproduce el crash |
| `physics_step` | (vacío) | `0.002` para desarrollo |
| `world` | `empty.world` | nombre en `yahboom_rosmaster_gazebo/worlds` o ruta absoluta |
| `gui` / `rviz` / `headless` | `true` / `true` / `false` | |
| `motion_profile` | `stress` | `ideal` para la línea base sin deslizamiento |
| `motion_bias` | `false` | deriva de motores sin calibrar |

---

# Parte 5 — Teleoperación

```bash
ros2 launch jar_bringup teleop.launch.py
```

Abre un xterm propio: `ros2 launch` no puede pasarle la terminal de control a
un proceso hijo, y el nodo lee teclas en crudo.

```
     q  w  e         w/s : adelante / atrás     q/e : diagonal
     a  s  d         a/d : desplazamiento lateral
     j     l         j/l : rotar CCW / CW
   espacio / k : frenar    z/x : más lento / más rápido    Ctrl-C : salir
```

**Por qué no `teleop_twist_keyboard`:** la versión de Humble (2.4.1) bloquea en
`stdin.read(1)`, emite un Twist por tecla y no tiene `repeat_rate`. Contra el
timeout de 0.5 s del watchdog, una tecla mantenida da tirones alrededor del
retardo de autorepetición de la terminal.

El nodo de `jar_bringup` publica en continuo y trata cada tecla como refresco
del comando por `key_timeout` (0.8 s), que cubre de sobra la autorepetición.

---

# Parte 6 — Validar sin humano

```bash
ros2 run jar_bringup drive_check
```

Recorre un tramo por cada grado de libertad mecanum e imprime el desplazamiento
medido por `/ground_truth/odom` (lo que pasó) y `/odom` (lo que el robot cree).
La diferencia entre ambos en los tramos de desplazamiento lateral y rotación es
el deslizamiento que inyecta el perfil `stress`, no una falla.

Cada fila debe corresponder a su propio eje: `forward` con `dx` positivo,
`strafe left` con `dy` positivo, `rotate ccw` con `dyaw` positivo.

> **Cerrá el teleop antes de correrlo.** Dos publicadores en `/cmd_vel` se
> pisan: el teleop emite ceros a 20 Hz cuando no hay tecla apretada, y esos
> ceros se intercalan con los comandos del probe. El watchdog reemite el
> último que llegó, el robot da un tirón y se queda quieto. `drive_check`
> detecta el conflicto y aborta antes de medir, en vez de reportar un FAIL
> que apunta al lugar equivocado.

> **Si los resultados aparecen corridos una fila, el reloj está roto.** Es el
> síntoma exacto de la Parte 1: los comandos llegan tarde y MecanumDrive
> arrastra el anterior al tramo siguiente.

---

# Parte 7 — Problemas conocidos

## `/dev/shm`: matar con `kill -9` rompe la corrida siguiente

FastDDS guarda su transporte de memoria compartida en `/dev/shm`. Una
simulación matada con `SIGKILL` deja esos segmentos bloqueados y la corrida
siguiente falla el discovery:

```
RTPS_TRANSPORT_SHM Error: Failed init_port fastrtps_port7423: open_and_lock_file failed
```

Los topics aparecen en `ros2 topic list` pero no llega nada, y el cliente GUI
puede segfaultear al arrancar. Con todos los procesos ROS apagados:

```bash
rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*
```

**Salí siempre con Ctrl+C.** El launch del fork tiene un handler que apaga los
bridges y Gazebo en el orden correcto.

## La cámara en RViz no muestra nada

La config del fork pide QoS `Reliable` para `/cam_1/color/image_raw`, pero su
propio relay publica `Best Effort`. En el log:

```
[rviz]: New publisher discovered on topic '/cam_1/color/image_raw', offering incompatible QoS
```

Arreglo manual: en RViz, display **Camera** → **Topic** → **Reliability
Policy** → `Best Effort`. No persiste, porque el fork impone su config.

El LaserScan sí está bien configurado; `/scan` se ve.

## Ruido que se puede ignorar

| Mensaje | Qué es |
|---|---|
| `QStandardPaths: wrong permissions on runtime directory /run/user/1000` | Cosmético de WSL. `chmod 700 /run/user/1000` lo calla |
| `Desired controller update period (0.0333 s) is slower than the gazebo simulation period` | Esperado, el broadcaster corre a 30 Hz |
| `NodeShared::Publish() Error: Interrupted system call` | Ruido de apagado con Ctrl+C |

---

# Para llevar al club (upstream)

Cosas que idealmente se arreglan en el fork y hoy obligan a los rodeos de acá:

1. **El launch no expone `--render-engine`.** Si aceptara un argumento
   `render_engine` y lo pasara a `ign gazebo`, no haría falta generar copias
   del world.
2. **`calculated_odometry.py` cuesta casi un core.** Corre con `use_sim_time` y
   procesa ~1000 callbacks/s de `/clock` en Python. Es instrumentación de
   debug; debería throttlearse o volverse condicional por argumento de launch.
3. **El QoS de la cámara en `rviz/gazebo.rviz` está mal**: pide `Reliable`
   contra un publisher `Best Effort`.

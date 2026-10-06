# Enjambre de 3 carritos con ACO en ESP32 + gemelo digital en PyBullet

```
 MUNDO FÍSICO                  PARTE DE RED                    PARTE VIRTUAL (Docker)
 ESP32 C1 ─┐                                                   ┌─ gemelo.py (PyBullet)
 ESP32 C2 ─┼── UDP 5005 ──►  ESP32 #4 MODO AP  ── UDP ──►      │   3 robots virtuales
 ESP32 C3 ─┘  "fer","pos"    SSID ENJAMBRE_ACO   difunde        │   feromonas en el piso
              ◄── "inicio","ir"  192.168.4.1     feromonas      └─ simulador_esp32.py
```

Cada carrito corre su **propia colonia de hormigas** (`aco.py`) y cada iteración publica
sus depósitos de feromona. El AP (`hub.py`) los reenvía a los otros 2 carritos y al gemelo,
así las 3 tablas de feromona se fusionan (estigmergia por red). Cuando los 3 convergen,
el hub envía la mejor ruta global y los carritos la recorren con salida escalonada
(3 s entre cada uno), quedando en fila india en la meta.

## Estructura

| Carpeta | Va en | Archivos |
|---|---|---|
| `esp32_comun/` | **las 4 ESP32** y el PC | `laberinto.py`, `aco.py`, `protocolo.py` |
| `esp32_ap/` | ESP32 #4 (AP) | `main.py`, `hub.py` |
| `esp32_carrito/` | ESP32 C1, C2, C3 | `main.py`, `config.py`, `carrito.py`, `motores.py` |
| `gemelo_pybullet/` | PC / Docker | `gemelo.py`, `simulador_esp32.py`, `Dockerfile` |
| `simulacion/` | navegador | `enjambre_aco.html` (simulación interactiva) |

## 1. Cargar las ESP32 (MicroPython ≥ 1.20)

Con `mpremote` (o Pymakr / Thonny):

```bash
# ESP32 #4 — punto de acceso
mpremote connect COM5 cp esp32_comun/*.py :  + cp esp32_ap/*.py :
# Cada carrito (cambia ID_CARRITO = 1, 2, 3 en config.py ANTES de copiar)
mpremote connect COM6 cp esp32_comun/*.py :  + cp esp32_carrito/*.py :
```

Orden de encendido: primero el AP (LED parpadea lento), luego los carritos.
Cuando los 3 se registran el AP pasa a EXPLORA (LED rápido) y después a EJECUTA (LED fijo).
Si quieres arrancar con botón, pon `AUTO_INICIO = False` en `esp32_ap/main.py` y presiona BOOT.

### Conexión del puente H (L298N) — valores por defecto de `config.py`

| L298N | ESP32 | | L298N | ESP32 |
|---|---|---|---|---|
| IN1 | GPIO26 | | IN3 | GPIO25 |
| IN2 | GPIO27 | | IN4 | GPIO33 |
| ENA (quitar jumper) | GPIO14 | | ENB (quitar jumper) | GPIO32 |
| GND | GND (común con la batería) | | 12V | batería 7.4 V |

### Calibración (por carrito)
1. `T_CELDA_MS`: tiempo que tarda en avanzar exactamente `TAM_CELDA_M` (30 cm por defecto).
2. `T_GIRO90_MS`: tiempo de un giro de 90° sobre su eje.
3. Si se desvía en recta, baja `CORR_IZQ` o `CORR_DER` (ej. 0.93).
4. `RUMBO_INICIAL`: hacia dónde mira el carrito en la casilla A.

## 2. Gemelo digital

**Sin hardware (demo):**
```bash
docker compose up --build gemelo-sim      # graba salida/gemelo_sim.gif
# o sin Docker:
pip install -r gemelo_pybullet/requirements.txt
python gemelo_pybullet/gemelo.py --sim    # ventana 3D de PyBullet
```

**Con las ESP32 reales:** conecta el PC al WiFi `ENJAMBRE_ACO` (clave `hormigas123`) y:
```bash
docker compose up gemelo                  # graba salida/gemelo_real.gif
python gemelo_pybullet/gemelo.py --hub-ip 192.168.4.1   # ventana 3D (fuera de Docker)
```
En la ventana: `i` fuerza el inicio, `q` sale.
Modo híbrido (1 carrito real + 2 emulados):
`python gemelo_pybullet/simulador_esp32.py --sin-hub --hub-ip 192.168.4.1 --carritos 2,3`

> Ventana 3D dentro de Docker: solo en Linux con X11 (`xhost +local:` y
> `docker compose --profile gui up gemelo-gui`). En Windows es más simple correr
> `gemelo.py` directo con Python (`pip install pybullet` o `conda install -c conda-forge pybullet`).

## 3. Protocolo (JSON por UDP, puerto 5005)

| Mensaje | De → a | Contenido |
|---|---|---|
| `hb` | carrito → hub | latido cada 1 s con estado, iteración y L |
| `fer` | carrito → hub → todos | depósitos `[[arista, Δτ], ...]` + mejor ruta de la iteración |
| `listo` | carrito → hub | convergió (L sin mejorar 12 iteraciones, mínimo 15) |
| `inicio` / `ir` | hub → carritos | arrancar ACO / ejecutar ruta global (se reenvían cada 1 s) |
| `pos`, `meta` | carrito → hub → gemelo | movimiento real para replicar en PyBullet |
| `hola`, `estado` | gemelo ↔ hub | registro del gemelo / estado global para el HUD |

## 4. ACO usado
`p(i→j) ∝ τ^α · η^β`, con η = 1/(distancia Manhattan a la meta + 1).
Hormigas con retroceso (siempre llegan y sin ciclos), evaporación `ρ = 0.15`,
depósito `Q/L` (Q = 1), refuerzo elitista ×2 de la mejor ruta y límites `τ ∈ [0.05, 10]`.
Para cambiar el laberinto edita `MAPA` en `laberinto.py` y cópialo a las 4 ESP32.

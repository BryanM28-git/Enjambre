# gemelo.py  -  Gemelo digital en PyBullet del enjambre ACO de 3 carritos
#
# - Se registra en el hub (ESP32 en modo AP) por UDP y recibe:
#     "fer"    -> feromonas que publica cada carrito  (se pintan en el piso)
#     "pos"    -> movimiento real de cada carrito     (el robot virtual lo replica)
#     "estado" -> fase global y estado de cada carrito (HUD)
# - Las "hormigas" de cada iteración se ven como esferas que recorren la ruta.
#
# Uso:
#   python gemelo.py --sim                     # todo emulado en el PC (sin hardware)
#   python gemelo.py --hub-ip 192.168.4.1      # con las ESP32 reales (PC conectado al AP)
#   python gemelo.py --sim --modo direct --grabar salida/gemelo.gif --salir-al-terminar
# Teclas (modo GUI): i = forzar inicio de la exploración, q = salir

import os
import sys
import math
import time
import queue
import socket
import argparse
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "esp32_comun"))

import pybullet as p                                                   # noqa: E402
import pybullet_data                                                   # noqa: E402
from laberinto import (MAPA, FILAS, COLS, INICIO, META, TAM_CELDA_M,   # noqa: E402
                       coord, todas_las_aristas)
from protocolo import PUERTO, codificar, decodificar                   # noqa: E402

T = TAM_CELDA_M
COLORES = {1: (0.90, 0.15, 0.15), 2: (0.15, 0.45, 0.95), 3: (0.10, 0.70, 0.30)}
YAW = (math.pi / 2, 0.0, -math.pi / 2, math.pi)        # N, E, S, O
RHO = 0.15


def xy(celda):
    f, c = coord(celda)
    return c * T, (FILAS - 1 - f) * T


def env(nombre, defecto):
    return os.environ.get(nombre, defecto)


# =================================================================== red
class Red(threading.Thread):
    def __init__(self, hub_ip, puerto_local):
        super().__init__(daemon=True)
        self.hub = (hub_ip, PUERTO)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1" if hub_ip == "127.0.0.1" else "0.0.0.0", puerto_local))
        self.s.settimeout(0.2)
        self.q = queue.Queue()
        self.cmd = None
        self.recibidos = 0

    def run(self):
        t_hola = 0
        while True:
            if time.time() - t_hola > 2 or self.cmd:
                msg = {"t": "hola", "id": "G"}
                if self.cmd:
                    msg["cmd"], self.cmd = self.cmd, None
                try:
                    self.s.sendto(codificar(msg), self.hub)
                except OSError:
                    pass
                t_hola = time.time()
            try:
                datos, _ = self.s.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            m = decodificar(datos)
            if m:
                self.recibidos += 1
                self.q.put(m)


# ============================================================== robot
class RobotVirtual:
    def __init__(self, cid, celda):
        r, g, b = COLORES.get(cid, (0.8, 0.8, 0.2))
        L, A, H = 0.09, 0.06, 0.03             # medio largo, medio ancho, medio alto
        rueda = [0.025, 0.012, 0.025]
        vis = p.createVisualShapeArray(
            shapeTypes=[p.GEOM_BOX] * 6,
            halfExtents=[[L, A, H], [0.02, A * 0.8, 0.012], rueda, rueda, rueda, rueda],
            rgbaColors=[[r, g, b, 1], [1, 1, 1, 1]] + [[0.1, 0.1, 0.1, 1]] * 4,
            visualFramePositions=[[0, 0, 0], [L - 0.02, 0, H + 0.01],
                                  [L * 0.6, A + 0.012, -0.01], [L * 0.6, -A - 0.012, -0.01],
                                  [-L * 0.6, A + 0.012, -0.01], [-L * 0.6, -A - 0.012, -0.01]])
        col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[L, A, H])
        self.cid = cid
        x, y = xy(celda)
        off = (cid - 2) * 0.09                 # en el inicio esperan uno al lado del otro
        self.x, self.y, self.yaw = x - 0.06, y + off, 0.0
        self.body = p.createMultiBody(0, col, vis, [self.x, self.y, 0.05])
        self.segs = []                          # cola de (x, y, yaw, dur_s)
        self.seg = None
        self._aplicar()

    def _aplicar(self):
        p.resetBasePositionAndOrientation(self.body, [self.x, self.y, 0.05],
                                          p.getQuaternionFromEuler([0, 0, self.yaw]))

    def mover(self, celda_a, d, ms):
        x, y = xy(celda_a)
        self.segs.append((x, y, YAW[d], max(ms, 50) / 1000.0))

    def actualizar(self, ahora):
        if self.seg is None and self.segs:
            x1, y1, yaw1, dur = self.segs.pop(0)
            if len(self.segs) > 2:              # si vamos atrasados, acelerar
                dur *= 0.4
            dyaw = (yaw1 - self.yaw + math.pi) % (2 * math.pi) - math.pi
            self.seg = (ahora, dur, self.x, self.y, self.yaw, x1, y1, dyaw)
        if self.seg:
            t0, dur, x0, y0, yaw0, x1, y1, dyaw = self.seg
            a = min(1.0, (ahora - t0) / dur)
            s = a * a * (3 - 2 * a)            # suavizado (smoothstep)
            self.x, self.y = x0 + (x1 - x0) * s, y0 + (y1 - y0) * s
            self.yaw = yaw0 + dyaw * s
            self._aplicar()
            if a >= 1.0:
                self.seg = None


class Hormiga:
    """Esfera que recorre la mejor ruta de la última iteración de un carrito."""
    VEL = 22.0                                  # celdas por segundo

    def __init__(self, cid):
        r, g, b = COLORES.get(cid, (0.8, 0.8, 0.2))
        vis = p.createVisualShape(p.GEOM_SPHERE, radius=0.03, rgbaColor=[r, g, b, 1])
        self.body = p.createMultiBody(0, -1, vis, [0, 0, -1])
        self.ruta = None
        self.t0 = 0

    def lanzar(self, ruta, ahora):
        if self.ruta is None:                   # no interrumpir la que va en camino
            self.ruta, self.t0 = ruta, ahora

    def actualizar(self, ahora):
        if not self.ruta:
            return
        k = (ahora - self.t0) * self.VEL
        if k >= len(self.ruta) - 1:
            self.ruta = None
            p.resetBasePositionAndOrientation(self.body, [0, 0, -1], [0, 0, 0, 1])
            return
        i = int(k)
        f = k - i
        xa, ya = xy(self.ruta[i])
        xb, yb = xy(self.ruta[i + 1])
        p.resetBasePositionAndOrientation(
            self.body, [xa + (xb - xa) * f, ya + (yb - ya) * f, 0.04], [0, 0, 0, 1])


# ============================================================== mundo
class Gemelo:
    def __init__(self, args):
        self.args = args
        self.gui = args.modo == "gui"
        p.connect(p.GUI if self.gui else p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        if self.gui:
            p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
        self.cx, self.cy = (COLS - 1) * T / 2, (FILAS - 1) * T / 2
        self.cam = dict(cameraDistance=max(FILAS, COLS) * T * 1.25, cameraYaw=0,
                        cameraPitch=-62, cameraTargetPosition=[self.cx, self.cy - 0.25, 0])
        if self.gui:
            p.resetDebugVisualizerCamera(**self.cam)
        self._construir()
        self.robots = {}
        self.hormigas = {}
        self.estado = {"fase": "ESPERA", "carritos": {}, "L": 0, "paquetes": 0}
        self.ruta_global = None
        self.t_meta = None
        self.hud_ids = []
        self.frames = []

    # ------------------------------------------------------------ escena
    def _construir(self):
        plano = p.loadURDF("plane.urdf")
        p.changeVisualShape(plano, -1, rgbaColor=[0.93, 0.93, 0.90, 1])
        h = 0.08
        col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[T / 2, T / 2, h])
        vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[T / 2, T / 2, h],
                                  rgbaColor=[0.20, 0.27, 0.40, 1])
        for f in range(FILAS):
            for c in range(COLS):
                if MAPA[f][c] == "#":
                    p.createMultiBody(0, col, vis, [c * T, (FILAS - 1 - f) * T, h])
        # baldosas de feromona: una por arista del grafo
        self.tau = {}
        self.baldosa = {}
        self.color_baldosa = {}
        for e in todas_las_aristas():
            i, d = e // 4, e % 4
            j = i + 1 if d == 1 else i + COLS
            (xa, ya), (xb, yb) = xy(i), xy(j)
            ext = [T * 0.55, T * 0.12, 0.002] if d == 1 else [T * 0.12, T * 0.55, 0.002]
            v = p.createVisualShape(p.GEOM_BOX, halfExtents=ext, rgbaColor=[0.85, 0.85, 0.82, 1])
            self.baldosa[e] = p.createMultiBody(0, -1, v, [(xa + xb) / 2, (ya + yb) / 2, 0.002])
            self.tau[e] = 1.0
            self.color_baldosa[e] = None
        # inicio (verde) y meta (bandera a cuadros)
        xa, ya = xy(INICIO)
        v = p.createVisualShape(p.GEOM_BOX, halfExtents=[T * 0.45, T * 0.45, 0.003],
                                rgbaColor=[0.2, 0.8, 0.3, 1])
        p.createMultiBody(0, -1, v, [xa, ya, 0.003])
        xm, ym = xy(META)
        n, lado = 4, T * 0.9 / 4
        vb = p.createVisualShape(p.GEOM_BOX, halfExtents=[lado / 2, lado / 2, 0.004], rgbaColor=[1, 1, 1, 1])
        vn = p.createVisualShape(p.GEOM_BOX, halfExtents=[lado / 2, lado / 2, 0.004], rgbaColor=[0, 0, 0, 1])
        for a in range(n):
            for b in range(n):
                p.createMultiBody(0, -1, vb if (a + b) % 2 else vn,
                                  [xm - T * 0.45 + lado * (a + 0.5), ym - T * 0.45 + lado * (b + 0.5), 0.004])
        vp = p.createVisualShape(p.GEOM_CYLINDER, radius=0.01, length=0.35, rgbaColor=[0.9, 0.5, 0.2, 1])
        for s in (-1, 1):
            p.createMultiBody(0, -1, vp, [xm + s * T * 0.45, ym + T * 0.45, 0.175])

    def _robot(self, cid):
        if cid not in self.robots:
            self.robots[cid] = RobotVirtual(cid, INICIO)
            self.hormigas[cid] = Hormiga(cid)
        return self.robots[cid]

    # ------------------------------------------------------- mensajes
    def procesar(self, m, ahora):
        t = m.get("t")
        cid = m.get("id")
        if t == "fer":
            self._robot(cid)
            f = (1 - RHO) ** (1.0 / 3)          # evaporación repartida entre 3 carritos
            for e in self.tau:
                self.tau[e] = max(0.05, self.tau[e] * f)
            for e, d in m.get("dep", []):
                if e in self.tau:
                    self.tau[e] = min(10.0, self.tau[e] + d)
            if m.get("ruta") and self.estado["fase"] == "EXPLORA":
                self.hormigas[cid].lanzar(m["ruta"], ahora)
        elif t == "pos":
            self._robot(cid).mover(m["a"], m["dir"], m.get("ms", 900))
        elif t == "estado":
            self.estado = m
            self.ruta_global = m.get("ruta")
            for k in m.get("carritos", {}):
                self._robot(int(k))

    def _pintar_feromona(self):
        tmax = max(self.tau.values()) or 1.0
        for e, v in self.tau.items():
            n = min(1.0, v / tmax)
            n = round(n * 10) / 10             # 11 niveles -> pocas llamadas
            if n == self.color_baldosa[e]:
                continue
            self.color_baldosa[e] = n
            # gris -> amarillo -> naranja -> rojo oscuro
            r = 0.85 + 0.15 * min(1, n * 2) - 0.35 * max(0, n - 0.5) * 2
            g = 0.85 - 0.15 * min(1, n * 2) - 0.55 * max(0, n - 0.5) * 2
            b = 0.82 - 0.75 * min(1, n * 1.5)
            p.changeVisualShape(self.baldosa[e], -1, rgbaColor=[r, max(0.1, g), max(0.05, b), 1])

    # ---------------------------------------------------------- HUD
    def _texto_hud(self):
        e = self.estado
        lineas = ["Fase: %s   Mejor L = %s celdas   Paquetes hub: %s"
                  % (e.get("fase"), e.get("L") or "-", e.get("paquetes", 0))]
        for k in sorted(e.get("carritos", {}), key=int):
            c = e["carritos"][k]
            lineas.append("C%s  %-8s it=%-3s L=%s" % (k, c["est"], c["it"], c["L"] or "-"))
        return lineas

    def _hud_gui(self):
        for i, txt in enumerate(self._texto_hud()):
            pos = [-0.2, (FILAS + 0.6) * T - i * 0.13, 0.3]
            col = [0, 0, 0] if i == 0 else list(COLORES.get(i, (0, 0, 0)))
            if i < len(self.hud_ids):
                p.addUserDebugText(txt, pos, col, 1.3, replaceItemUniqueId=self.hud_ids[i])
            else:
                self.hud_ids.append(p.addUserDebugText(txt, pos, col, 1.3))

    def _capturar(self):
        import numpy as np
        from PIL import Image, ImageDraw
        w, h = self.args.ancho, int(self.args.ancho * 0.75)
        vm = p.computeViewMatrixFromYawPitchRoll(self.cam["cameraTargetPosition"],
                                                 self.cam["cameraDistance"],
                                                 self.cam["cameraYaw"], self.cam["cameraPitch"], 0, 2)
        pm = p.computeProjectionMatrixFOV(60, w / h, 0.05, 30)
        rend = p.ER_BULLET_HARDWARE_OPENGL if self.gui else p.ER_TINY_RENDERER
        img = p.getCameraImage(w, h, vm, pm, renderer=rend)[2]
        arr = np.reshape(np.array(img, dtype=np.uint8), (h, w, 4))[:, :, :3]
        im = Image.fromarray(arr)
        dr = ImageDraw.Draw(im)
        for i, txt in enumerate(self._texto_hud()):
            col = (0, 0, 0) if i == 0 else tuple(int(255 * v) for v in COLORES.get(i, (0, 0, 0)))
            dr.text((8, 6 + 14 * i), txt, fill=col)
        self.frames.append(im.quantize(colors=128))

    def _guardar_video(self):
        if not self.frames:
            return
        ruta = self.args.grabar
        os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
        ms = int(1000 / self.args.fps)
        self.frames[0].save(ruta, save_all=True, append_images=self.frames[1:],
                            duration=ms, loop=0, optimize=True)
        print("[GEMELO] video guardado en %s (%d cuadros)" % (ruta, len(self.frames)))

    # ---------------------------------------------------------- bucle
    def correr(self, red):
        t_ini = time.time()
        t_pinta = t_hud = t_frame = 0
        try:
            while True:
                ahora = time.time()
                while not red.q.empty():
                    self.procesar(red.q.get(), ahora)
                for r in self.robots.values():
                    r.actualizar(ahora)
                for h in self.hormigas.values():
                    h.actualizar(ahora)
                if ahora - t_pinta > 0.2:
                    t_pinta = ahora
                    self._pintar_feromona()
                if self.gui:
                    if ahora - t_hud > 0.5:
                        t_hud = ahora
                        self._hud_gui()
                    teclas = p.getKeyboardEvents()
                    if ord("i") in teclas:
                        red.cmd = "inicio"
                    if ord("q") in teclas:
                        break
                if self.args.grabar and ahora - t_frame >= 1.0 / self.args.fps:
                    t_frame = ahora
                    self._capturar()
                # fin automático
                cs = self.estado.get("carritos", {})
                quietos = all(r.seg is None and not r.segs for r in self.robots.values())
                if cs and all(c["est"] == "META" for c in cs.values()) and quietos:
                    if self.t_meta is None:
                        self.t_meta = ahora
                        print("[GEMELO] los 3 carritos llegaron a la meta")
                    elif self.args.salir_al_terminar and ahora - self.t_meta > 2:
                        break
                if self.args.duracion and ahora - t_ini > self.args.duracion:
                    break
                p.stepSimulation()
                time.sleep(1 / 120)
        except KeyboardInterrupt:
            pass
        if self.args.grabar:
            self._guardar_video()
        print("[GEMELO] mensajes recibidos: %d" % red.recibidos)
        p.disconnect()


def main():
    ap = argparse.ArgumentParser(description="Gemelo digital PyBullet del enjambre ACO")
    ap.add_argument("--hub-ip", default=env("HUB_IP", "192.168.4.1"))
    ap.add_argument("--puerto-local", type=int, default=int(env("PUERTO_LOCAL", "5010")))
    ap.add_argument("--modo", choices=["gui", "direct"], default=env("MODO", "gui"))
    ap.add_argument("--sim", action="store_true", default=env("SIM", "0") == "1",
                    help="emular hub + 3 carritos en el PC")
    ap.add_argument("--grabar", default=env("GRABAR", ""), help="ruta .gif para grabar")
    ap.add_argument("--fps", type=int, default=int(env("FPS", "8")))
    ap.add_argument("--ancho", type=int, default=int(env("ANCHO", "560")))
    ap.add_argument("--duracion", type=float, default=float(env("DURACION", "0")))
    ap.add_argument("--salir-al-terminar", action="store_true",
                    default=env("SALIR_AL_TERMINAR", "0") == "1")
    args = ap.parse_args()

    hub = None
    if args.sim:
        import simulador_esp32
        args.hub_ip = "127.0.0.1"
        hub = simulador_esp32.lanzar_hub("127.0.0.1")
    print("[GEMELO] conectando al hub %s:%d  modo=%s" % (args.hub_ip, PUERTO, args.modo))
    g = Gemelo(args)
    red = Red(args.hub_ip, args.puerto_local)
    red.start()
    if hub is not None:
        # en simulación, los carritos arrancan cuando el gemelo ya está registrado
        t0 = time.time()
        while not hub.gemelos and time.time() - t0 < 5:
            time.sleep(0.05)
        for cid in (1, 2, 3):
            simulador_esp32.lanzar_carrito(cid, "127.0.0.1")
    g.correr(red)


if __name__ == "__main__":
    main()

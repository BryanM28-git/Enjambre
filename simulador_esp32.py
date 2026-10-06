# simulador_esp32.py  -  Emula en el PC las 4 ESP32 (hub AP + 3 carritos)
# Usa EXACTAMENTE el mismo código MicroPython (hub.py, carrito.py, aco.py ...)
# pero con sockets UDP reales en localhost y motores simulados (solo esperas).
#
#   python simulador_esp32.py                      # hub + 3 carritos en 127.0.0.1
#   python simulador_esp32.py --carritos 2,3 --sin-hub --hub-ip 192.168.4.1
#        -> modo híbrido: hub y carrito 1 reales, carritos 2 y 3 emulados

import os
import sys
import socket
import threading
import time
import argparse

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("esp32_comun", "esp32_ap", "esp32_carrito"):
    sys.path.insert(0, os.path.join(RAIZ, sub))

from protocolo import PUERTO, NUM_CARRITOS      # noqa: E402
from hub import Hub                             # noqa: E402
from carrito import Carrito                     # noqa: E402


class MotoresSim:
    """Sustituye a motores.Motores: solo espera el tiempo del movimiento."""

    def __init__(self, t_celda_ms=900, t_giro90_ms=420, escala=1.0):
        self.t_celda = int(t_celda_ms * escala)     # ms reportados al gemelo
        self.t_giro = int(t_giro90_ms * escala)

    def avanzar_celda(self):
        time.sleep(self.t_celda / 1000)

    def girar(self, cuartos):
        time.sleep(self.t_giro * abs(cuartos) / 1000)

    def parar(self, freno_ms=0):
        pass


def _log(prefijo):
    def f(txt):
        print(prefijo + txt, flush=True)
    return f


def lanzar_hub(ip="127.0.0.1", puerto=PUERTO, n=NUM_CARRITOS, verbose=True):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((ip, puerto))
    s.settimeout(0)
    hub = Hub(s, n, log=_log("") if verbose else (lambda t: None))

    def ciclo():
        while True:
            hub.tick()
            time.sleep(0.005)
    threading.Thread(target=ciclo, daemon=True, name="hub").start()
    return hub


def lanzar_carrito(cid, hub_ip="127.0.0.1", puerto=PUERTO, escala=1.0,
                   periodo_it_ms=250, verbose=True):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0" if hub_ip != "127.0.0.1" else "127.0.0.1", 0))
    s.settimeout(0)
    params = {"alfa": 1.0, "beta": 2.0, "rho": 0.15, "q": 1.0,
              "n_hormigas": 6, "elitismo": 2.0, "semilla": cid * 7919}
    c = Carrito(cid, s, (hub_ip, puerto), MotoresSim(escala=escala),
                params_aco=params, periodo_it_ms=periodo_it_ms, rumbo_inicial=1,
                log=_log("") if verbose else (lambda t: None))
    threading.Thread(target=c.correr, daemon=True, name="carrito%d" % cid).start()
    return c


def iniciar(hub_ip="127.0.0.1", carritos=(1, 2, 3), con_hub=True, escala=1.0,
            verbose=True):
    hub = lanzar_hub(hub_ip) if con_hub else None
    time.sleep(0.2)
    cs = [lanzar_carrito(i, hub_ip, escala=escala, verbose=verbose) for i in carritos]
    return hub, cs


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Emulador de las ESP32 del enjambre ACO")
    ap.add_argument("--hub-ip", default="127.0.0.1")
    ap.add_argument("--carritos", default="1,2,3")
    ap.add_argument("--sin-hub", action="store_true", help="usar el hub real (ESP32 AP)")
    ap.add_argument("--escala", type=float, default=1.0, help="factor de tiempo de los motores")
    a = ap.parse_args()
    ids = [int(x) for x in a.carritos.split(",") if x]
    hub, cs = iniciar(a.hub_ip, ids, not a.sin_hub, a.escala)
    try:
        while True:
            time.sleep(1)
            if cs and all(c.estado == "META" for c in cs):
                print("== Todos los carritos llegaron. Fin de la simulación ==")
                break
    except KeyboardInterrupt:
        pass

# protocolo.py  -  Mensajes UDP/JSON entre carritos, ESP32-AP (hub) y gemelo digital
#
#  Carrito -> Hub   {"t":"hb",   "id":1, "est":"EXPLORA", "it":12, "L":18}    latido (cada 1 s)
#  Carrito -> Hub   {"t":"fer",  "id":1, "it":12, "dep":[[e,d],...], "ruta":[...], "L":18}
#  Carrito -> Hub   {"t":"listo","id":1, "ruta":[...], "L":18}
#  Carrito -> Hub   {"t":"pos",  "id":1, "de":c0, "a":c1, "dir":d, "ms":900}
#  Gemelo  -> Hub   {"t":"hola", "id":"G"}                                    registro (cada 2 s)
#  Hub -> todos     reenvía "fer" y "pos" (difusión de feromonas)
#  Hub -> carritos  {"t":"inicio"}                      arranca la exploración ACO
#  Hub -> carritos  {"t":"ir", "ruta":[...], "L":18, "orden":[1,2,3]}  ejecutar ruta óptima
#  Hub -> gemelo    {"t":"estado", "carritos":{...}, "fase":"..."}

import json

SSID = "ENJAMBRE_ACO"
CLAVE = "hormigas123"
IP_HUB = "192.168.4.1"
PUERTO = 5005
NUM_CARRITOS = 3

try:                                    # MicroPython
    from time import ticks_ms, ticks_diff, sleep_ms
except ImportError:                     # CPython (PC / Docker)
    import time as _t

    def ticks_ms():
        return int(_t.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

    def sleep_ms(ms):
        _t.sleep(ms / 1000)


def codificar(msg):
    return json.dumps(msg).encode()


def decodificar(datos):
    try:
        return json.loads(datos)
    except Exception:
        return None


def recibir_todo(sock, maximo=20):
    """Lee sin bloquear todos los paquetes pendientes del socket."""
    salida = []
    for _ in range(maximo):
        try:
            datos, addr = sock.recvfrom(2048)
        except OSError:          # EAGAIN / timeout -> no hay más
            break
        m = decodificar(datos)
        if m is not None:
            salida.append((m, addr))
    return salida

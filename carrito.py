# carrito.py  -  Lógica de un carrito del enjambre (máquina de estados)
#
#   ESPERA  --"inicio"-->  EXPLORA  --converge-->  LISTO  --"ir"-->  EJECUTA  -->  META
#
# EXPLORA: corre ACO localmente, publica sus depósitos de feromona y aplica
#          los depósitos que llegan de los otros 2 carritos (vía el hub).
# EJECUTA: recorre físicamente la mejor ruta global, celda por celda,
#          reportando su posición para que el gemelo digital la replique.
# Mismo código para la ESP32 (MicroPython) y para el simulador en PC.

from protocolo import codificar, recibir_todo, ticks_ms, ticks_diff, sleep_ms
from aco import ColoniaACO
from laberinto import VECINOS, NOMBRE_DIR


class Carrito:
    def __init__(self, id_carrito, sock, hub_addr, motores,
                 params_aco=None, periodo_it_ms=250, min_it=15,
                 paciencia=12, max_it=80, peso_externo=1.0,
                 rumbo_inicial=1, log=print):
        self.id = id_carrito
        self.sock = sock
        self.hub = hub_addr
        self.mot = motores
        self.aco = ColoniaACO(**(params_aco or {}))
        self.periodo = periodo_it_ms
        self.min_it, self.paciencia, self.max_it = min_it, paciencia, max_it
        self.peso_ext = peso_externo
        self.rumbo = rumbo_inicial          # 0=N 1=E 2=S 3=O
        self.log = log
        self.estado = "ESPERA"
        self.sin_mejora = 0
        self.t_it = 0
        self.t_hb = 0
        self.ruta_final = None
        self.t_salida = 0
        self.paso = 0
        self.parada = 0                     # índice de la celda donde se detiene
        self.recibidos = 0

    # ---------------------------------------------------------------- red
    def enviar(self, msg):
        msg["id"] = self.id
        try:
            self.sock.sendto(codificar(msg), self.hub)
        except OSError:
            pass

    def latido(self, forzar=False):
        ahora = ticks_ms()
        if forzar or ticks_diff(ahora, self.t_hb) >= 1000:
            self.t_hb = ahora
            self.enviar({"t": "hb", "est": self.estado, "it": self.aco.iteracion,
                         "L": self.aco.mejor_L if self.aco.mejor_ruta else 0})

    def atender_red(self):
        for m, _ in recibir_todo(self.sock):
            t = m.get("t")
            if t == "inicio" and self.estado == "ESPERA":
                self.log("[C%d] inicio de exploración ACO" % self.id)
                self.estado = "EXPLORA"
                self.latido(True)
            elif t == "fer" and m.get("id") != self.id:
                # estigmergia: las feromonas de los otros carritos se suman a las mías
                self.aco.aplicar(m.get("dep", []), self.peso_ext)
                if self.aco.considerar_ruta(m.get("ruta")):
                    self.sin_mejora = 0
                self.recibidos += 1
            elif t == "ir" and self.estado in ("LISTO", "EXPLORA"):
                self._preparar_ejecucion(m)

    # ------------------------------------------------------------ explorar
    def _iterar(self):
        L_antes = self.aco.mejor_L
        dep, mejor_it = self.aco.iterar()
        self.sin_mejora = 0 if self.aco.mejor_L < L_antes else self.sin_mejora + 1
        # se comparte solo lo que cambió en esta iteración (paquete pequeño)
        dep_lista = [[e, round(d, 3)] for e, d in dep.items()]
        self.enviar({"t": "fer", "it": self.aco.iteracion, "dep": dep_lista,
                     "ruta": mejor_it, "L": self.aco.mejor_L})
        it = self.aco.iteracion
        convergio = (it >= self.min_it and self.sin_mejora >= self.paciencia)
        if convergio or it >= self.max_it:
            self.estado = "LISTO"
            self.log("[C%d] LISTO en it=%d  L=%d  (paquetes recibidos=%d)"
                     % (self.id, it, self.aco.mejor_L, self.recibidos))
            self.enviar({"t": "listo", "ruta": self.aco.mejor_ruta, "L": self.aco.mejor_L})
            self.latido(True)

    # ------------------------------------------------------------ ejecutar
    def _preparar_ejecucion(self, m):
        self.ruta_final = m["ruta"]
        orden = m.get("orden", [self.id])
        k = orden.index(self.id) if self.id in orden else 0
        # salida escalonada y "fila india" en la meta para no chocar entre sí
        self.t_salida = ticks_ms() + k * m.get("retardo_ms", 3000)
        self.parada = max(0, len(self.ruta_final) - 1 - k)
        self.paso = 0
        self.estado = "EJECUTA"
        self.log("[C%d] ejecutando ruta L=%d (sale en %d ms, se detiene en paso %d)"
                 % (self.id, m.get("L", 0), k * m.get("retardo_ms", 3000), self.parada))
        self.enviar({"t": "pos", "de": self.ruta_final[0], "a": self.ruta_final[0],
                     "dir": self.rumbo, "ms": 0})
        self.latido(True)

    def _mover_un_paso(self):
        i, j = self.ruta_final[self.paso], self.ruta_final[self.paso + 1]
        d = -1
        for dd, v in VECINOS[i]:
            if v == j:
                d = dd
        giro = (d - self.rumbo) % 4            # 0 recto, 1 der, 2 media vuelta, 3 izq
        cuartos = (0, 1, 2, -1)[giro]
        if cuartos:
            self.enviar({"t": "pos", "de": i, "a": i, "dir": d,
                         "ms": self.mot.t_giro * abs(cuartos)})
            self.mot.girar(cuartos)
            self.rumbo = d
        self.enviar({"t": "pos", "de": i, "a": j, "dir": d, "ms": self.mot.t_celda})
        self.mot.avanzar_celda()
        self.paso += 1
        self.log("[C%d] celda %d -> %d (%s)" % (self.id, i, j, NOMBRE_DIR[d]))

    # ---------------------------------------------------------- ciclo
    def tick(self):
        self.atender_red()
        self.latido()
        ahora = ticks_ms()
        if self.estado == "EXPLORA" and ticks_diff(ahora, self.t_it) >= self.periodo:
            self.t_it = ahora
            self._iterar()
        elif self.estado == "EJECUTA" and ticks_diff(ahora, self.t_salida) >= 0:
            if self.paso < self.parada:
                self._mover_un_paso()
            else:
                self.mot.parar()
                self.estado = "META"
                self.enviar({"t": "meta", "celda": self.ruta_final[self.paso]})
                self.latido(True)
                self.log("[C%d] llegó a su posición final" % self.id)

    def correr(self):
        while True:
            self.tick()
            sleep_ms(10)

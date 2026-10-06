# hub.py  -  Lógica del nodo central (ESP32 en modo AP)
# - Registra a los 3 carritos y al gemelo digital
# - Difunde las feromonas que publica cada carrito a los demás (estigmergia por red)
# - Lleva la mejor ruta global y da la orden de ejecutarla
# Funciona igual en MicroPython (ESP32) y en CPython (simulador_esp32.py).

from protocolo import codificar, recibir_todo, ticks_ms, ticks_diff, NUM_CARRITOS


class Hub:
    def __init__(self, sock, num_carritos=NUM_CARRITOS, auto_inicio=True,
                 retardo_salida_ms=3000, timeout_explora_ms=60000, log=print):
        self.sock = sock
        self.n = num_carritos
        self.auto = auto_inicio
        self.retardo = retardo_salida_ms
        self.timeout = timeout_explora_ms
        self.log = log
        self.carritos = {}        # id -> {"addr", "est", "it", "L"}
        self.gemelos = {}         # addr -> ticks del último "hola"
        self.fase = "ESPERA"
        self.t_fase = ticks_ms()
        self.t_tick = 0
        self.mejor_ruta = None
        self.mejor_L = 1 << 30
        self.paquetes = 0

    # ------------------------------------------------------------ envío
    def _enviar(self, msg, addr):
        try:
            self.sock.sendto(codificar(msg), addr)
        except OSError:
            pass

    def _difundir(self, msg, excepto=None):
        datos = codificar(msg)
        destinos = [c["addr"] for c in self.carritos.values()] + list(self.gemelos.keys())
        for a in destinos:
            if a != excepto:
                try:
                    self.sock.sendto(datos, a)
                except OSError:
                    pass

    def _a_gemelos(self, msg):
        for a in self.gemelos:
            self._enviar(msg, a)

    def _cambiar_fase(self, f):
        self.log("[HUB] fase %s -> %s" % (self.fase, f))
        self.fase = f
        self.t_fase = ticks_ms()

    # ---------------------------------------------------------- recepción
    def _actualizar_mejor(self, ruta, L):
        if ruta and L < self.mejor_L:
            self.mejor_L = L
            self.mejor_ruta = ruta
            self.log("[HUB] nueva mejor ruta global L=%d" % L)

    def procesar(self, m, addr):
        self.paquetes += 1
        t = m.get("t")
        if t == "hola":
            if addr not in self.gemelos:
                self.log("[HUB] gemelo digital registrado %s" % (addr,))
            self.gemelos[addr] = ticks_ms()
            if m.get("cmd") == "inicio" and self.fase == "ESPERA":
                self._cambiar_fase("EXPLORA")
            return
        cid = m.get("id")
        if cid is None:
            return
        c = self.carritos.get(cid)
        if c is None:
            self.log("[HUB] carrito %s registrado %s" % (cid, addr))
            c = {"addr": addr, "est": "ESPERA", "it": 0, "L": 0}
            self.carritos[cid] = c
        c["addr"] = addr
        if t == "hb":
            c["est"] = m.get("est", c["est"])
            c["it"] = m.get("it", 0)
            c["L"] = m.get("L", 0)
        elif t == "fer":
            c["it"] = m.get("it", 0)
            self._actualizar_mejor(m.get("ruta"), m.get("L", 1 << 30))
            self._difundir(m, excepto=addr)        # feromonas -> otros carritos + gemelo
        elif t == "listo":
            c["est"] = "LISTO"
            self._actualizar_mejor(m.get("ruta"), m.get("L", 1 << 30))
            self.log("[HUB] carrito %s LISTO (L=%s)" % (cid, m.get("L")))
        elif t == "pos" or t == "meta":
            if t == "meta":
                c["est"] = "META"
            self._a_gemelos(m)

    # -------------------------------------------------------------- tick
    def tick(self):
        for m, addr in recibir_todo(self.sock):
            self.procesar(m, addr)
        ahora = ticks_ms()
        if ticks_diff(ahora, self.t_tick) < 1000:
            return
        self.t_tick = ahora

        if self.fase == "ESPERA":
            if self.auto and len(self.carritos) >= self.n:
                self._cambiar_fase("EXPLORA")

        if self.fase == "EXPLORA":
            # (re)envía "inicio" a quien siga esperando (UDP puede perder paquetes)
            for c in self.carritos.values():
                if c["est"] == "ESPERA":
                    self._enviar({"t": "inicio"}, c["addr"])
            listos = [k for k, c in self.carritos.items() if c["est"] in ("LISTO", "EJECUTA", "META")]
            vencido = ticks_diff(ahora, self.t_fase) > self.timeout and listos
            if (len(listos) >= self.n or vencido) and self.mejor_ruta:
                self._cambiar_fase("EJECUTA")

        if self.fase == "EJECUTA":
            orden = sorted(self.carritos.keys())
            for k in orden:
                c = self.carritos[k]
                if c["est"] in ("LISTO", "EXPLORA"):
                    self._enviar({"t": "ir", "ruta": self.mejor_ruta, "L": self.mejor_L,
                                  "orden": orden, "retardo_ms": self.retardo}, c["addr"])

        estado = {}
        for k, c in self.carritos.items():
            estado[str(k)] = {"est": c["est"], "it": c["it"], "L": c["L"]}
        self._a_gemelos({"t": "estado", "fase": self.fase, "carritos": estado,
                         "L": self.mejor_L if self.mejor_ruta else 0,
                         "ruta": self.mejor_ruta, "paquetes": self.paquetes})

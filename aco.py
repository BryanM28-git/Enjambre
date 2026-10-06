# aco.py  -  Optimización por Colonia de Hormigas (ACO) sobre el laberinto
# Corre DENTRO de cada ESP32 (MicroPython) y también en el PC (simulador).
#
# Variante usada: Ant System elitista con límites de feromona (estilo MAX-MIN)
#   p(i->j) = tau_ij^alfa * eta_j^beta / sum(...)
#   tau <- (1-rho)*tau + sum(Q / L_k)  (+ refuerzo elitista de la mejor ruta)
#
# Cada hormiga hace un recorrido aleatorio guiado por feromona con
# retroceso (backtracking): si llega a un callejón sin salida se devuelve,
# así SIEMPRE encuentra la meta y la ruta final no tiene ciclos.

import random
from laberinto import (N_CELDAS, VECINOS, ETA, INICIO, META,
                       arista, todas_las_aristas)


class ColoniaACO:
    def __init__(self, alfa=1.0, beta=2.0, rho=0.15, q=1.0,
                 n_hormigas=6, elitismo=2.0, tau0=1.0,
                 tau_min=0.05, tau_max=10.0, semilla=None):
        self.alfa = alfa
        self.beta = beta
        self.rho = rho
        self.q = q
        self.n_hormigas = n_hormigas
        self.elitismo = elitismo
        self.tau_min = tau_min
        self.tau_max = tau_max
        if semilla is not None:
            random.seed(semilla)
        self.tau = [0.0] * (N_CELDAS * 4)
        self.aristas = todas_las_aristas()
        for e in self.aristas:
            self.tau[e] = tau0
        # eta^beta precalculado (ahorra potencias en la ESP32)
        self.eta_b = [e ** beta for e in ETA]
        self.mejor_ruta = None
        self.mejor_L = 1 << 30
        self.iteracion = 0

    # ----------------------------------------------------------- hormiga
    def construir_ruta(self):
        visit = bytearray(N_CELDAS)
        pila = [INICIO]
        visit[INICIO] = 1
        tau, a, eta_b = self.tau, self.alfa, self.eta_b
        while pila[-1] != META:
            i = pila[-1]
            cands = []
            total = 0.0
            for d, j in VECINOS[i]:
                if not visit[j]:
                    w = (tau[arista(i, d)] ** a) * eta_b[j]
                    cands.append((j, w))
                    total += w
            if not cands:            # callejón sin salida -> retroceder
                pila.pop()
                if not pila:
                    return None      # la meta no es alcanzable
                continue
            r = random.random() * total
            elegido = cands[-1][0]
            for j, w in cands:
                r -= w
                if r <= 0:
                    elegido = j
                    break
            visit[elegido] = 1
            pila.append(elegido)
        return pila

    # ------------------------------------------------------- feromonas
    def _depositar(self, dep, ruta, cantidad):
        for k in range(len(ruta) - 1):
            i, j = ruta[k], ruta[k + 1]
            for d, v in VECINOS[i]:
                if v == j:
                    e = arista(i, d)
                    dep[e] = dep.get(e, 0.0) + cantidad
                    break

    def evaporar(self):
        f = 1.0 - self.rho
        tau, tmin = self.tau, self.tau_min
        for e in self.aristas:
            v = tau[e] * f
            tau[e] = v if v > tmin else tmin

    def aplicar(self, depositos, peso=1.0):
        """Suma depósitos {arista: delta} (propios o recibidos por red)."""
        tau, tmax = self.tau, self.tau_max
        for e, d in depositos.items() if isinstance(depositos, dict) else depositos:
            v = tau[e] + d * peso
            tau[e] = v if v < tmax else tmax

    # -------------------------------------------------------- iteración
    def iterar(self):
        """Una iteración completa. Devuelve (depositos, mejor_ruta_iter).
        'depositos' es lo que se comparte por red con los otros carritos."""
        self.iteracion += 1
        dep = {}
        mejor_it = None
        for _ in range(self.n_hormigas):
            ruta = self.construir_ruta()
            if ruta is None:
                continue
            L = len(ruta) - 1
            self._depositar(dep, ruta, self.q / L)
            if mejor_it is None or L < len(mejor_it) - 1:
                mejor_it = ruta
        if mejor_it is not None and len(mejor_it) - 1 < self.mejor_L:
            self.mejor_L = len(mejor_it) - 1
            self.mejor_ruta = mejor_it
        if self.mejor_ruta is not None and self.elitismo > 0:
            self._depositar(dep, self.mejor_ruta, self.elitismo * self.q / self.mejor_L)
        self.evaporar()
        self.aplicar(dep)
        return dep, mejor_it

    def considerar_ruta(self, ruta):
        """Si otro carrito encontró una ruta mejor, la adoptamos como elite."""
        if ruta and len(ruta) - 1 < self.mejor_L and ruta[0] == INICIO and ruta[-1] == META:
            self.mejor_L = len(ruta) - 1
            self.mejor_ruta = list(ruta)
            return True
        return False

    def ruta_greedy(self):
        """Ruta siguiendo la feromona más alta (para verificar convergencia)."""
        visit = bytearray(N_CELDAS)
        ruta = [INICIO]
        visit[INICIO] = 1
        while ruta[-1] != META and len(ruta) < N_CELDAS:
            i = ruta[-1]
            mejor, mt = -1, -1.0
            for d, j in VECINOS[i]:
                if not visit[j] and self.tau[arista(i, d)] > mt:
                    mejor, mt = j, self.tau[arista(i, d)]
            if mejor < 0:
                return None
            visit[mejor] = 1
            ruta.append(mejor)
        return ruta

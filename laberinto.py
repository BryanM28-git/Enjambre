# laberinto.py  -  Mapa compartido por los 3 carritos, el AP y el gemelo digital
# Compatible con MicroPython (ESP32) y CPython (PC / Docker).
#
#   '#' = pared     '.' = celda libre     'A' = punto de inicio     'M' = meta
#
# Cada celda del mapa equivale a un cuadro del laberinto físico (ver TAM_CELDA_M).
# Si cambias el mapa, cópialo IGUAL en las 4 ESP32 y en el gemelo.

MAPA = (
    "###########",
    "#A....#...#",
    "#.##.##.#.#",
    "#.#.....#.#",
    "#.#.###.#.#",
    "#...#...#.#",
    "###.#.###.#",
    "#...#.....#",
    "#.###.###.#",
    "#.....#..M#",
    "###########",
)

TAM_CELDA_M = 0.30          # lado de cada celda en metros (laberinto físico)

FILAS = len(MAPA)
COLS = len(MAPA[0])
N_CELDAS = FILAS * COLS

# Direcciones: 0 = Norte, 1 = Este, 2 = Sur, 3 = Oeste
DIRS = ((-1, 0), (0, 1), (1, 0), (0, -1))
NOMBRE_DIR = ("N", "E", "S", "O")


def coord(i):
    """Índice de celda -> (fila, columna)."""
    return i // COLS, i % COLS


def indice(f, c):
    return f * COLS + c


def libre(f, c):
    return 0 <= f < FILAS and 0 <= c < COLS and MAPA[f][c] != "#"


def _buscar(ch):
    for f in range(FILAS):
        c = MAPA[f].find(ch)
        if c >= 0:
            return indice(f, c)
    raise ValueError("No se encontró '%s' en el mapa" % ch)


INICIO = _buscar("A")
META = _buscar("M")

# VECINOS[i] = lista de (direccion, celda_vecina) solo para celdas libres
VECINOS = []
for _i in range(N_CELDAS):
    _f, _c = coord(_i)
    _v = []
    if libre(_f, _c):
        for _d in range(4):
            _df, _dc = DIRS[_d]
            if libre(_f + _df, _c + _dc):
                _v.append((_d, indice(_f + _df, _c + _dc)))
    VECINOS.append(_v)

# Información heurística (eta): inversa de la distancia Manhattan a la meta
_fm, _cm = coord(META)
ETA = [1.0 / (abs(coord(i)[0] - _fm) + abs(coord(i)[1] - _cm) + 1) for i in range(N_CELDAS)]


def arista(i, d):
    """Id canónico de la arista que sale de la celda i en dirección d.
    Se guarda siempre como (celda, E) o (celda, S) para que i->j y j->i
    sean la MISMA arista (feromona simétrica)."""
    if d == 0:          # Norte  -> es el Sur de la celda de arriba
        return (i - COLS) * 4 + 2
    if d == 3:          # Oeste  -> es el Este de la celda de la izquierda
        return (i - 1) * 4 + 1
    return i * 4 + d


def direccion(i, j):
    """Dirección para ir de la celda i a la celda vecina j."""
    for d, k in VECINOS[i]:
        if k == j:
            return d
    return -1


def aristas_de_ruta(ruta):
    return [arista(ruta[k], direccion(ruta[k], ruta[k + 1])) for k in range(len(ruta) - 1)]


def todas_las_aristas():
    """Lista de ids canónicos de todas las aristas del grafo."""
    s = []
    for i in range(N_CELDAS):
        for d, j in VECINOS[i]:
            if d in (1, 2):
                s.append(i * 4 + d)
    return s

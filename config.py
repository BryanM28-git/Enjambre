# config.py  -  ÚNICO archivo que cambia entre los 3 carritos
ID_CARRITO = 1              # 1, 2 o 3  (¡distinto en cada ESP32!)

# Pines del puente H (L298N). Ajusta a tu cableado.
PIN_IN1, PIN_IN2 = 26, 27   # motor izquierdo
PIN_IN3, PIN_IN4 = 25, 33   # motor derecho
PIN_ENA, PIN_ENB = 14, 32   # PWM izquierdo / derecho
PIN_LED = 2

# Calibración (medir en el piso real con el carrito cargado)
VELOCIDAD = 0.65            # 0..1 (duty del PWM)
T_CELDA_MS = 900            # tiempo para avanzar 1 celda (TAM_CELDA_M en laberinto.py)
T_GIRO90_MS = 420           # tiempo para girar 90° sobre su eje
CORR_IZQ = 1.00             # compensa diferencias entre motores (ej. 0.95)
CORR_DER = 1.00

RUMBO_INICIAL = 1           # hacia dónde mira el carrito en 'A': 0=N 1=E 2=S 3=O

# Parámetros ACO (iguales en los 3 carritos; semilla distinta = exploración diversa)
PARAMS_ACO = {
    "alfa": 1.0,            # peso de la feromona
    "beta": 2.0,            # peso de la heurística (distancia a la meta)
    "rho": 0.15,            # evaporación
    "q": 1.0,               # cantidad de feromona depositada (Q/L por hormiga)
    "n_hormigas": 6,        # hormigas por iteración EN CADA carrito
    "elitismo": 2.0,
    "semilla": ID_CARRITO * 7919,
}
PERIODO_IT_MS = 250         # una iteración ACO cada 250 ms

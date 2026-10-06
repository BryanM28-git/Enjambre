# main.py  -  ESP32 de cada carrito (1, 2 y 3)
# Archivos que deben estar en esta ESP32:
#   main.py, config.py, carrito.py, motores.py      (esp32_carrito/)
#   aco.py, laberinto.py, protocolo.py              (esp32_comun/)

import network
import socket
from machine import Pin
import config as cfg
from protocolo import SSID, CLAVE, IP_HUB, PUERTO, sleep_ms
from motores import Motores
from carrito import Carrito

led = Pin(cfg.PIN_LED, Pin.OUT)

mot = Motores(cfg.PIN_IN1, cfg.PIN_IN2, cfg.PIN_IN3, cfg.PIN_IN4,
              cfg.PIN_ENA, cfg.PIN_ENB, vel=cfg.VELOCIDAD,
              t_celda_ms=cfg.T_CELDA_MS, t_giro90_ms=cfg.T_GIRO90_MS,
              corr_izq=cfg.CORR_IZQ, corr_der=cfg.CORR_DER)

# ------------------------------------------- conexión al AP (ESP32 #4)
sta = network.WLAN(network.STA_IF)
sta.active(True)
if not sta.isconnected():
    print("Conectando a", SSID, "...")
    sta.connect(SSID, CLAVE)
    n = 0
    while not sta.isconnected():
        led.value(not led.value())
        sleep_ms(250)
        n += 1
        if n % 40 == 0:                  # reintenta cada 10 s
            sta.disconnect()
            sta.connect(SSID, CLAVE)
led.on()
print("Carrito %d conectado:" % cfg.ID_CARRITO, sta.ifconfig())

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", PUERTO + cfg.ID_CARRITO))
s.settimeout(0)

c = Carrito(cfg.ID_CARRITO, s, (IP_HUB, PUERTO), mot,
            params_aco=cfg.PARAMS_ACO, periodo_it_ms=cfg.PERIODO_IT_MS,
            rumbo_inicial=cfg.RUMBO_INICIAL)

try:
    c.correr()
except KeyboardInterrupt:
    mot.parar()
    print("Detenido")

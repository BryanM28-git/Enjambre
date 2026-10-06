# motores.py  -  Control de 2 motores DC con puente H (L298N / TB6612FNG / L9110)
# Movimiento por celdas: avanzar 1 celda y girar 90°/180° calibrados por tiempo.
# (Si tu carrito tiene encoders, reemplaza avanzar_celda/girar por lazo cerrado.)

from machine import Pin, PWM
from protocolo import sleep_ms


class Motores:
    def __init__(self, in1, in2, in3, in4, ena, enb,
                 vel=0.65, t_celda_ms=900, t_giro90_ms=420,
                 corr_izq=1.0, corr_der=1.0, freq=1000):
        self.in1, self.in2 = Pin(in1, Pin.OUT), Pin(in2, Pin.OUT)
        self.in3, self.in4 = Pin(in3, Pin.OUT), Pin(in4, Pin.OUT)
        self.ena = PWM(Pin(ena), freq=freq)
        self.enb = PWM(Pin(enb), freq=freq)
        self.vel = vel
        self.t_celda = t_celda_ms
        self.t_giro = t_giro90_ms
        self.ci, self.cd = corr_izq, corr_der
        self.parar()

    @staticmethod
    def _duty(pwm, v):
        v = max(0.0, min(1.0, v))
        pwm.duty_u16(int(v * 65535))

    def _motor(self, a, b, pwm, v):
        """v en [-1, 1]; signo = sentido de giro."""
        if v > 0:
            a.on(); b.off()
        elif v < 0:
            a.off(); b.on()
        else:
            a.off(); b.off()
        self._duty(pwm, abs(v))

    def ruedas(self, izq, der):
        self._motor(self.in1, self.in2, self.ena, izq * self.ci)
        self._motor(self.in3, self.in4, self.enb, der * self.cd)

    def parar(self, freno_ms=0):
        self.ruedas(0, 0)
        if freno_ms:
            sleep_ms(freno_ms)

    def _rampa(self, izq, der, ms):
        # arranque suave (evita que las ruedas patinen y descalibren el tiempo)
        pasos = 5
        for k in range(1, pasos + 1):
            self.ruedas(izq * k / pasos, der * k / pasos)
            sleep_ms(20)
        sleep_ms(max(0, ms - 20 * pasos))
        self.parar(80)

    def avanzar_celda(self):
        self._rampa(self.vel, self.vel, self.t_celda)

    def girar(self, cuartos):
        """cuartos: +1 = 90° derecha, -1 = 90° izquierda, 2 = 180°."""
        if cuartos == 0:
            return
        s = 1 if cuartos > 0 else -1
        self._rampa(self.vel * s, -self.vel * s, self.t_giro * abs(cuartos))

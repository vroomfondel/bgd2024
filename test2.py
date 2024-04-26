import machine
import time


p=machine.Pin(1, machine.Pin.OUT)

for i in range(0, 100):
    p.value(0)
    time.sleep(1)
    p.value(1)
    time.sleep(1)

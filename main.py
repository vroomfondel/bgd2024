import logging
import micropython

micropython.alloc_emergency_exception_buf(100)

# serial stuff also here: https://github.com/micropython/micropython/blob/master/tools/pyboard.py

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

logger.debug("STARTING main.py")

import io
import sys
import time
import math
from time import sleep

from machine import Timer
import machine

import mqttwrap
import wifi
import config

MEASURE_TELE_PERIOD: int = 300

if not config.DISABLE_INET:
    wifi.ensure_wifi()
    mqttwrap.ensure_mqtt_connect()

msgtimer: Timer = Timer(0)
lightdowntimer: Timer = Timer(1)
reboottimer: Timer = Timer(2)
# esp32: four hardware-timers available

import _thread

lock = _thread.allocate_lock()


def reboot_callback(trigger):
    micropython.schedule(reboot_trigger, None)


def reboot_trigger(_=None):
    timestring: str = time.getisotimenow()
    logger.info(f"{timestring}::rebooting...")
    mqttwrap.publish_one(
        topic=mqttwrap.get_feed("loggingfeed"),
        msg=f"rebooting at {timestring}",
        retain=True,
        qos=1,
    )
    time.sleep(1)
    machine.reset()


def check_msgs(_=None):
    global lock

    if config.DISABLE_INET:
        return

    # logger.debug("check_msgs")

    if lock.locked():
        logger.debug("LOCKED...")

    try:
        with lock:
            wifi.ensure_wifi_catch_reset(reset_if_wifi_fails=True)
            mqttwrap.ensure_mqtt_catch_reset(reset_if_mqtt_fails=True)

            mqttwrap.check_msgs()

            ts_cmd_arg: tuple[int, str, str | None] | None = None

            while True:
                ts_cmd_arg = mqttwrap.pop_cmd_received()
                if ts_cmd_arg is None:
                    break

                cmd: str = ts_cmd_arg[1]
                if cmd == "reboot" or cmd == "reset":
                    logger.info("reboot command received...")
                    reboot_trigger()
                elif cmd == "switchap":
                    logger.info("switchap command received...")
                elif cmd == "rescanwifi":
                    logger.info("rescanwifi command received...")
                else:
                    logger.warning(f"unknown command: {cmd} arg={ts_cmd_arg[2]}")
    except Exception as ex:
        _out = io.StringIO()
        sys.print_exception(ex)
        sys.print_exception(ex, _out)

        logger.error(_out.getvalue())


def check_msgs_callback(trigger):
    # logger.debug(f"{type(trigger)=} {trigger=}")
    # DEBUG:__main__:type(trigger)=<class 'Timer'> trigger=Timer(0, mode=PERIODIC, period=3000)
    micropython.schedule(check_msgs, None)


############################# end of boilerplate #############################


last_measure_sent_gmt: float | None = None
last_measure_sent_data: dict | None = None

from ssd1306 import SSD1306_I2C
from sh1106 import SH1106_I2C

import boot_ssd
ssd: SH1106_I2C | SSD1306_I2C | None = boot_ssd.ssd
sdapin: machine.Pin | None = boot_ssd.sdapin
sclpin: machine.Pin | None = boot_ssd.sclpin
soft_i2cbus: machine.SoftI2C | None = boot_ssd.soft_i2cbus
boot_ssd.disable()


adc_input_pin: machine.Pin | None = None
digital_input_pin: machine.Pin | None = None

wakeup_deepsleep_pin: machine.Pin | None = None

input_adc: machine.ADC | None = None

output_pin: machine.Pin | None = None

output_pin_pwm: machine.Pin | None = None
output_pwm: machine.PWM | None = None

uart2: machine.UART | None = None
pin_low: bool = False


# def handle_pin_interrupt_rising(pin: machine.Pin):
#     global pin_low, pin_high
#     pin_low = False
#     pin_high = True
#     print("RISING")

def handle_pin_interrupt_falling_rising(arg_pin: machine.Pin):
    global pin_low
    v: float | bool | int = arg_pin.value()
    pin_low = 0 == v
    logger.debug(f"handle_pin_value :: {v} {arg_pin=}")


def setup_pins():
    global adc_input_pin, digital_input_pin, input_adc, pin_low, output_pin, output_pin_pwm, output_pwm, uart2
    global soft_i2cbus, sdapin, sclpin, ssd, wakeup_deepsleep_pin

    # generally usable pins ( https://www.youtube.com/watch?v=LY-1DHTxRAk  |  https://drive.google.com/file/d/1gbKM7DA7PI7s1-ne_VomcjOrb0bE2TPZ/view )
    # 04, 05, 16, 17, 18, 19, 23, 25, 26, 27, 32, 33

    # RTC_GPIO0 (GPIO36)
    # RTC_GPIO3 (GPIO39)
    # RTC_GPIO4 (GPIO34)
    # RTC_GPIO5 (GPIO35)
    # RTC_GPIO6 (GPIO25)
    # RTC_GPIO7 (GPIO26)
    # RTC_GPIO8 (GPIO33)
    # RTC_GPIO9 (GPIO32)
    # RTC_GPIO10 (GPIO4)
    # RTC_GPIO11 (GPIO0)
    # RTC_GPIO12 (GPIO2)
    # RTC_GPIO13 (GPIO15)
    # RTC_GPIO14 (GPIO13)
    # RTC_GPIO15 (GPIO12)
    # RTC_GPIO16 (GPIO14)
    # RTC_GPIO17 (GPIO27)

    # IO34	I	GPIO34	No	RTC_GPIO04	ADC1_CH06
    # IO35	I	GPIO35	No	RTC_GPIO05	ADC1_CH07
    # SENSOR_VP	I	GPIO36	No	RTC_GPIO00	ADC1_CH0
    # SENSOR_VN	I	GPIO39	No	RTC_GPIO03	ADC1_CH03

    # UART0: tx=1, rx=3
    # UART1: tx=10, rx=9
    # UART2: tx=17, rx=16

    logger.info("Setting up pins")

    if config.data["i2c"]["enabled"]:
        if not sdapin:
            sdapin = machine.Pin(config.data["i2c"]["sda_pin"])
        else:
            logger.debug("sdapin already created")

        if not sclpin:
            sclpin = machine.Pin(config.data["i2c"]["scl_pin"])
        else:
            logger.debug("sclpin already created")

        if not soft_i2cbus:
            soft_i2cbus = machine.SoftI2C(scl=sclpin, sda=sdapin)
            logger.debug(f"{soft_i2cbus=}")

            k: list = soft_i2cbus.scan()
            for i in k:
                logger.debug(f"i2c_scan: {i=}")
        else:
            logger.debug("i2c already created")

        if not ssd and config.data["ssd1306"]["enabled"]:
            flip_en: bool = False
            if "flip_en" in config.data["ssd1306"] and config.data["ssd1306"]["flip_en"]:
                flip_en = True

            ssd = SSD1306_I2C(width=config.data["ssd1306"]["width"], height=config.data["ssd1306"]["height"], i2c=soft_i2cbus, addr=config.data["ssd1306"]["address"])
            if flip_en:
                ssd.rotate(180)
                
            ssd.init_display()

            ssd.text(f"_SCREEN_INIT", 0, 0, 1)
            ssd.show()

        if not ssd and config.data["sh1106"]["enabled"]:
            flip_en: bool = config.data["sh1106"]["flip_en"]
            ssd = SH1106_I2C(width=config.data["sh1106"]["width"], height=config.data["sh1106"]["height"], i2c=soft_i2cbus, addr=config.data["sh1106"]["address"], rotate=180 if flip_en else 0)
            ssd.init_display()

            ssd.text(f"_SCREEN_INIT", 0, 0, 1)
            ssd.show()

    # TODO
    if config.data["rotary"]["enabled"]:
        ...

    if config.data["adc"]["enabled"]:
        pin: int = config.data["adc"]["input_pin"]
        adc_input_pin = machine.Pin(pin, machine.Pin.IN)

        logger.info(f"Setting up ADC on PIN {pin}")
        input_adc = machine.ADC(adc_input_pin, atten=machine.ADC.ATTN_11DB)  # TN_11DB)
        input_adc.width(machine.ADC.WIDTH_12BIT)
        # adc.atten(ADC.ATTN_11DB)       #Full range: 3.3v
        # ADC.ATTN_0DB: 0dB attenuation, gives a maximum input voltage of 1.00v - this is the default configuration
        # ADC.ATTN_2_5DB: 2.5dB attenuation, gives a maximum input voltage of approximately 1.34v
        # ADC.ATTN_6DB: 6dB attenuation, gives a maximum input voltage of approximately 2.00v
        # ADC.ATTN_11DB: 11dB attenuation, gives a maximum input voltage of approximately 3.6v

    if config.data["digital_output"]["enabled"]:
        pin: int = config.data["digital_output"]["output_pin"]
        logger.info(f"Setting up DIGITAL OUT on PIN {pin}")

        output_pin = machine.Pin(pin, machine.Pin.OUT)  # , pull=machine.Pin.PULL_DOWN)

    if config.data["digital_input"]["enabled"]:
        digital_input_pin = machine.Pin(config.data["digital_input"]["input_pin"])

        pin_low = digital_input_pin.value() == 0
        digital_input_pin.irq(trigger=machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING,
                              handler=handle_pin_interrupt_falling_rising)

    if False and config.data["wakeup_deepsleep_pin"]["enabled"]:
        import esp32
        
        wakeup_deepsleep_pin = machine.Pin(config.data["wakeup_deepsleep_pin"]["input_pin"])

        trigger_level = esp32.WAKEUP_ANY_HIGH
        if "trigger" in config.data["wakeup_deepsleep_pin"]:
            trigger_level = esp32.WAKEUP_ANY_HIGH if config.data["wakeup_deepsleep_pin"]["trigger"] == 1 else esp32.WAKEUP_ALL_LOW
            
        
        logger.info(f'setting external wakeup-signal to HIGH on PIN#{config.data["wakeup_deepsleep_pin"]["input_pin"]} {trigger_level=}')
        
            
        if not "disable_handler" in config.data["wakeup_deepsleep_pin"] or not config.data["wakeup_deepsleep_pin"]["disable_handler"]:
            wakeup_deepsleep_pin.irq(trigger=machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING,
                                 handler=handle_pin_interrupt_falling_rising)

        
        esp32.wake_on_ext0(wakeup_deepsleep_pin, trigger_level)

    if config.data["pwm"]["enabled"]:
        pin: int = config.data["pwm"]["output_pin"]
        logger.info(f"Setting up PWM on PIN {pin}")

        output_pin_pwm = machine.Pin(pin)
        output_pwm = machine.PWM(output_pin_pwm, duty=0, freq=50_000)

    if config.data["uart"]["enabled"]:
        rxpin: int = config.data["uart"]["rx_pin"]
        txpin: int = config.data["uart"]["tx_pin"]

        logger.info(f"Setting up UART on PINs {rxpin} + {txpin}")
        if rxpin == 16 and txpin == 17:
            uart2 = machine.UART(2)
            # uart2 = machine.UART(2, baudrate=115201, bits=8, parity=None, stop=1, tx=17, rx=16, rts=-1, cts=-1, txbuf=256, rxbuf=256, timeout=10, timeout_char=10)
            # default: UART(2, baudrate=115201, bits=8, parity=None, stop=1, tx=17, rx=16, rts=-1, cts=-1, txbuf=256, rxbuf=256, timeout=0, timeout_char=0)
            # uart2.init(9600, bits=8, parity=None, stop=1)
            uart2.init(timeout=5_000, timeout_char=100)
        else:
            uart2 = machine.UART(2, tx=txpin, rx=rxpin, baudrate=115200, bits=8, parity=None, stop=1, txbuf=256,
                                 rxbuf=256)
            # uart2 = machine.UART(2, baudrate=115201, bits=8, parity=None, stop=1, tx=17, rx=16, rts=-1, cts=-1, txbuf=256, rxbuf=256, timeout=10, timeout_char=10)
            # default: UART(2, baudrate=115201, bits=8, parity=None, stop=1, tx=17, rx=16, rts=-1, cts=-1, txbuf=256, rxbuf=256, timeout=0, timeout_char=0)
            # uart2.init(9600, bits=8, parity=None, stop=1)
            uart2.init(timeout=5_000, timeout_char=100)


def setup():
    global msgtimer, lightdowntimer

    logger.debug("main::setup()")

    check_msgs()

    setup_pins()

    msgtimer.init(
        period=3_000, mode=machine.Timer.PERIODIC, callback=check_msgs_callback
    )

    lightdowntimer.init(
        period=1_000, mode=machine.Timer.PERIODIC, callback=timer_callback
        #lambda x: logger.info("CALLED_MEASURE_TIMER_CALLBACK")
    )

    if config.data["forcerestart_after_running_seconds"] > 0:
        reboottimer.init(
            period=config.data["forcerestart_after_running_seconds"] * 1000,
            mode=machine.Timer.ONE_SHOT,
            callback=reboot_callback,
        )

    # tim2 = Timer(-1)
    # tim2.init(period=30000, mode=Timer.PERIODIC, callback=lambda t: mqttclient.ping())
    # tim.deinit()


# outpin: machine.Pin = machine.Pin(16, machine.Pin.OPEN_DRAIN)  #, pull=machine.Pin.PULL_UP)
# outpin_bistable_relais: bool = True



# deadline = time.ticks_add(time.ticks_ms(), 600_000)    
# while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        
import rotary_simple

showled: bool = False

deepsleepdeadline = None
timerdeadline = None
#deadline = ticks_add(time.ticks_ms(), 200)
timerleft: int|None = None
deepsleeptimerleft: int|None = None

def timer_tick(_=None):
    global timerleft, timerdeadline, deepsleepdeadline, deepsleeptimerleft, ssd
    
    if timerdeadline is not None:
        td = time.ticks_diff(timerdeadline, time.ticks_ms())
        timerleft = round(td / 1000.0)
        logger.debug(f"td: {td}\ttimerleft: {timerleft}\tis_deepsleepdeadline=False")
        
        if timerleft <= 0:
            send_light(0)
            timerleft = None
            timerdeadline = None
            
            deepsleepdeadline = time.ticks_add(time.ticks_ms(), 42 * 1_000)  # 42s


    if deepsleepdeadline is not None:
        td = time.ticks_diff(deepsleepdeadline, time.ticks_ms())
        deepsleeptimerleft = round(td / 1000.0)
        logger.debug(f"td: {td}\tdeepsleeptimerleft: {deepsleeptimerleft}\tis_deepsleepdeadline=True")
        
        if deepsleeptimerleft <= 0:
            rotary_simple.shutdown = True

def timer_callback(trigger):
    # logger.debug(f"{type(trigger)=} {trigger=}")
    # DEBUG:__main__:type(trigger)=<class 'Timer'> trigger=Timer(0, mode=PERIODIC, period=3000)
    micropython.schedule(timer_tick, None)
    
    
def send_light(value: int = 33):
    timestring: str = time.getisotimenow()
    logger.info(f"{timestring}::send_light...")
    
    logger.info(f"sende {value=} an: {mqttwrap.get_feed('lightswitchfeed')}")
        
    mqttwrap.publish_one(
        topic=mqttwrap.get_feed("lightswitchfeed"),
        msg=mqttwrap.value_to_mqtt_string(value),
        retain=True,
        qos=1,
    )    

rotary_value: int | None = None
def handle_rotary_click(pin: machine.Pin, threshold_ms: int = 20) -> None:
    global pin_low, ssd, rotary_value, timerdeadline, timerleft, deepsleepdeadline, deepsleeptimerleft

    conseq: int = 0
    loopcount: int = 0
    last_value: int = pin.value()
    while conseq < threshold_ms:
        loopcount += 1
        time.sleep_ms(1)
        cur_value: int = pin.value()

        if last_value == cur_value:
            conseq += 1
        else:
            conseq = 0

        last_value = cur_value

    pin_low = 0 == last_value

    logger.debug(f"handle_rotary_click::{pin_low=} after {loopcount} loops")
    
    if pin_low:
        if rotary_value == 0:
            logger.debug("deleting timer deadline")
            
            timerdeadline = None
            timerleft = None
                    
            # send_light(rotary_value)
        else:
            timerdeadline = time.ticks_add(time.ticks_ms(), rotary_value * 1_000 * 60)
            # timerdeadline in MINUTEN !!!
            logger.debug(f"timerdeadline set to: {timerdeadline}")
            timer_tick()
    

def handle_rotary_change(new_value: int, old_value: int):
    global rotary_value, ssd

    # rotary_value = new_value

    logger.debug(f"handle_rotary_change::{old_value=} => {new_value=}")

    x: int = 0
    y: int = 9
    ssd.fill_rect(x, y, ssd.width, 8, 0)
    ssd.text(f"{old_value} => {new_value}...", x, y, 1)
    y += 9
    ssd.show()


lastpaint: int|None = None
def handle_rotary_loop(cur_value: int|None):
    global rotary_value, ssd, timerleft, lastpaint, deepsleeptimerleft
    if cur_value == None:
        logger.debug("Got None => shutdown?!")
        return
        
    if rotary_value == cur_value:
        if lastpaint is not None:
            if time.ticks_add(lastpaint, 1_000) > time.ticks_ms():
                return
    
    rotary_value = cur_value

    x: int = 0
    y: int = 0
    ssd.fill_rect(x, y, ssd.width, 8, 0)
    ssd.fill_rect(x, y+17, ssd.width, 8, 0)
    ssd.text(f"VALUE: {cur_value}m...", x, y, 1)
    y += 9
    y += 9
    if timerleft is not None:
        timerleft_m = timerleft // 60
        timerleft_s = timerleft % 60
        ssd.text(f"TIMER: {timerleft_m}:{timerleft_s:02}", x, y, 1)
        y += 9
    elif deepsleeptimerleft is not None:
        timerleft_m = deepsleeptimerleft // 60
        timerleft_s = deepsleeptimerleft % 60
        ssd.text(f"SLEEP_IN: {timerleft_m}:{timerleft_s:02}", x, y, 1)
        y += 9
        
            
    ssd.show()
    
    lastpaint = time.ticks_ms()

    logger.debug(f"handle_rotary_loop::{cur_value=} {lastpaint=}")


def rotary_loop():
    global pin_low, ssd, rotary_value, wakeup_deepsleep_pin
    
    from rotary_irq_esp import RotaryIRQ
    
    #send_light(60)

    # perhaps check https://github.com/mchobby/micropython-oled-menu
    # for menu-styles ?!

    min_val: int = 0
    max_val: int = 3*60

    logger.info("started rotary_loop...")
    ssd.fill(0)
    x: int = 0
    y: int = 0
    ssd.text(f"VALUE: {min_val}...", x, y, 1)
    y += 8
    ssd.show()

    rotary_simple.rotary_loop(
        pin_num_clk=config.data["rotary"]["clk_pin"],
        pin_num_dt=config.data["rotary"]["dt_pin"],
        pin_num_sw=config.data["rotary"]["sw_pin"],
        min_val=min_val,
        max_val=max_val,
        reverse=True,
        range_mode=RotaryIRQ.RANGE_BOUNDED,
        click_handler=handle_rotary_click,
        change_handler=handle_rotary_change,
        loop_handler=handle_rotary_loop,
        init_value=15
    )
    
    logger.debug("AFTER ROTARY LOOP!")
    ## TODO esp shutdown here!
    config.DISABLE_INET = True
            
    logger.debug("DISABLING INET AND WIFI...")
    wifi.wlan.disconnect()
    wifi.wlan.active(False)
    ssd.poweroff()
    
    import esp32
    wakeup_deepsleep_pin = machine.Pin(config.data["wakeup_deepsleep_pin"]["input_pin"], pull=None)

    trigger_level = esp32.WAKEUP_ANY_HIGH
    if "trigger" in config.data["wakeup_deepsleep_pin"]:
        t = config.data["wakeup_deepsleep_pin"]["trigger"]
        logger.debug(f'{config.data["wakeup_deepsleep_pin"]["trigger"]=}')
        
        trigger_level = esp32.WAKEUP_ANY_HIGH if t == 1 else esp32.WAKEUP_ALL_LOW
        
    
    logger.info(f'setting external wakeup-signal to {trigger_level=} on PIN#{config.data["wakeup_deepsleep_pin"]["input_pin"]}')
    
    esp32.wake_on_ext0(wakeup_deepsleep_pin, trigger_level)

    machine.deepsleep()



if __name__ == "__main__":
    setup()
    
    logger.info(f"HOSTNAME: {config.data['hostname']}")

    if config.data["hostname"] == "josolightesp32":
        rotary_loop()

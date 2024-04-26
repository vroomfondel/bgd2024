import machine
import micropython

import time
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

try:
    from typing import Callable
except Exception as ex:
    logger.error(ex)

import sys

if sys.platform == 'esp8266' or sys.platform == 'esp32':
    from rotary_irq_esp import RotaryIRQ
else:
    logger.error('Warning:  The Rotary module has not been tested on this platform')

shutdown: bool = False

def rotary_loop(pin_num_clk=25,
                pin_num_dt=26,
                pin_num_sw=27,
                min_val=0,
                max_val=5,
                reverse=False,
                range_mode=RotaryIRQ.RANGE_WRAP,
                click_handler: Callable[[int], None] = None,
                change_handler: Callable[[int, int], None] = None,
                loop_handler: Callable[[int], None] = None,
                init_value:int|None = None
                ):

    global shutdown
    sw_pin: machine.Pin = machine.Pin(pin_num_sw, machine.Pin.IN, machine.Pin.PULL_UP)

    if click_handler:
        def click_handler_cb(pin: machine.Pin) -> None:
            micropython.schedule(click_handler, pin)
    else:
        def click_handler_cb(pin: machine.Pin) -> None:
            logger.debug(f"CLICKED {pin=} {pin.value()}")

    sw_pin.irq(click_handler_cb, trigger=machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING)

    try:
        r = RotaryIRQ(pin_num_clk=pin_num_clk,
                      pin_num_dt=pin_num_dt,
                      min_val=min_val,
                      max_val=max_val,
                      reverse=reverse,
                      range_mode=range_mode)
        
        r.set(value=init_value)

        val_old: int = r.value()
        while True:
            try:
                val_new: int = r.value()

                if val_old != val_new:
                    logger.debug(f'result ={val_new}')
                    if change_handler:
                        change_handler(val_new, val_old)

                    val_old = val_new

                if loop_handler:
                    loop_handler(val_new)
                        
                    if shutdown:
                        loop_handler(None)
                        break

                time.sleep_ms(50)
            except Exception as exx:
                import sys
                import io

                _out = io.StringIO()
                sys.print_exception(exx)
                sys.print_exception(exx, _out)

                logger.error(_out.getvalue())
                
                time.sleep_ms(50)            
    except Exception as ex:
        import sys
        import io

        _out = io.StringIO()
        sys.print_exception(ex)
        sys.print_exception(ex, _out)

        logger.error(_out.getvalue())
    finally:
        sw_pin.irq(handler=None)

import logging
import micropython

micropython.alloc_emergency_exception_buf(100)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

logger.debug("STARTING main.py")

import time
import machine

import mqttwrap
import wifi
import config

MEASURE_TELE_PERIOD: int = 300

if not config.DISABLE_INET:
    wifi.ensure_wifi()
    mqttwrap.ensure_mqtt_connect()
    
def sende_test():
    timestring: str = time.getisotimenow()
    logger.info(f"{timestring}::sende_test...")
    
    logger.info(f"sende an: {mqttwrap.get_feed('lightswitchfeed')}")
    
    value = 33
    
    mqttwrap.publish_one(
        topic=mqttwrap.get_feed("lightswitchfeed"),
        msg=mqttwrap.value_to_mqtt_string(value),
        retain=True,
        qos=1,
    )    


if __name__ == "__main__":
    print("WOOHOO")
    
    sende_test()
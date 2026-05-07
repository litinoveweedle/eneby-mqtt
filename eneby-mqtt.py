#! /usr/bin/python

from threading import Lock
import logging
import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO
import configparser
import operator
import json
import time
import uptime
import datetime
import re
import sys
import traceback
from typing import Any


# define user-defined exception
class AppError(Exception):
    "Raised on application error"

    pass


class MqttError(Exception):
    "Raised on MQTT connection failure"

    pass


# Setup logging
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# global variables
state = {"POWER": "OFF", "VOLUME": 0, "Time": 0, "Uptime": 0}

# read config
config = configparser.ConfigParser()
config.read("config.ini")

if "LOGGING" in config:
    if "LEVEL" in config["LOGGING"] and config["LOGGING"]["LEVEL"]:
        log_level = config["LOGGING"]["LEVEL"].upper()
        if log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            logger.setLevel(getattr(logging, log_level))
        else:
            raise AppError("Invalid logging level " + config["LOGGING"]["LEVEL"])

if "MQTT" in config:
    for key in [
        "TOPIC",
        "SERVER",
        "PORT",
        "QOS",
        "TIMEOUT",
        "USER",
        "PASS",
        "BIRTH_TOPIC",
    ]:
        if not config["MQTT"][key]:
            logger.error("Missing or empty config entry MQTT/" + key)
            raise AppError("Missing or empty config entry MQTT/" + key)
else:
    logger.error("Missing config section MQTT")
    raise AppError("Missing config section MQTT")

if "GPIO" in config:
    for key in ["POWER", "VOL_UP", "VOL_DW", "BT_LED", "AUX_LED"]:
        if not config["GPIO"][key]:
            logger.error("Missing or empty config entry GPIO/" + key)
            raise AppError("Missing or empty config entry GPIO/" + key)
else:
    logger.error("Missing config section GPIO")
    raise AppError("Missing config section GPIO")

if "VOLUME" in config:
    for key in ["MAXIMUM", "DEFAULT", "INITIAL"]:
        if not config["VOLUME"][key]:
            logger.error("Missing or empty config entry VOLUME/" + key)
            raise AppError("Missing or empty config entry VOLUME/" + key)
else:
    logger.error("Missing config section VOLUME")
    raise AppError("Missing config section VOLUME")

if "RUNTIME" in config:
    for key in ["MAX_ERROR", "RESTART_DELAY", "TELE_INTERVAL"]:
        if not config["RUNTIME"][key]:
            logger.error("Missing or empty config entry RUNTIME/" + key)
            raise AppError("Missing or empty config entry RUNTIME/" + key)
else:
    logger.error("Missing config section RUNTIME")
    raise AppError("Missing config section RUNTIME")


def set_power(state):
    if state == "ON" and not GPIO.input(int(config["GPIO"]["AUX_LED"])):
        logger.info("Sent power " + state)
        GPIO.setup(int(config["GPIO"]["POWER"]), GPIO.OUT, initial=GPIO.LOW)
        time.sleep(0.1)
        GPIO.setup(int(config["GPIO"]["POWER"]), GPIO.IN)
    elif state == "OFF" and GPIO.input(int(config["GPIO"]["AUX_LED"])):
        logger.info("Sent power " + state)
        GPIO.setup(int(config["GPIO"]["POWER"]), GPIO.OUT, initial=GPIO.LOW)
        time.sleep(0.1)
        GPIO.setup(int(config["GPIO"]["POWER"]), GPIO.IN)


def set_volume(count=0):
    if count > 0:
        if state["VOLUME"] == int(config["VOLUME"]["MAXIMUM"]):
            return True
        elif count > int(config["VOLUME"]["MAXIMUM"]) - state["VOLUME"]:
            count = int(config["VOLUME"]["MAXIMUM"]) - state["VOLUME"]
        logger.info("Sent volume +" + str(count))
    elif count < 0:
        if state["VOLUME"] == 0:
            return True
        elif count < 0 - state["VOLUME"]:
            count = 0 - state["VOLUME"]
        logger.info("Sent volume " + str(count))
    else:
        return True

    up = GPIO.input(int(config["GPIO"]["VOL_UP"]))
    dw = GPIO.input(int(config["GPIO"]["VOL_DW"]))

    if up and dw:
        GPIO.remove_event_detect(int(config["GPIO"]["VOL_UP"]))
        GPIO.remove_event_detect(int(config["GPIO"]["VOL_DW"]))
        time.sleep(0.01)
        GPIO.setup(int(config["GPIO"]["VOL_UP"]), GPIO.OUT, initial=GPIO.LOW)
        time.sleep(0.01)
        GPIO.setup(int(config["GPIO"]["VOL_DW"]), GPIO.OUT, initial=GPIO.LOW)
        time.sleep(0.01)
    elif not up and not dw:
        GPIO.remove_event_detect(int(config["GPIO"]["VOL_UP"]))
        GPIO.remove_event_detect(int(config["GPIO"]["VOL_DW"]))
        time.sleep(0.01)
        GPIO.setup(int(config["GPIO"]["VOL_UP"]), GPIO.OUT, initial=GPIO.HIGH)
        time.sleep(0.01)
        GPIO.setup(int(config["GPIO"]["VOL_DW"]), GPIO.OUT, initial=GPIO.HIGH)
        time.sleep(0.01)
    else:
        logger.error("Invalid encoder status")
        return False

    if count > 0:
        for x in range(0, count):
            up = operator.not_(up)
            dw = operator.not_(dw)
            GPIO.output(int(config["GPIO"]["VOL_UP"]), dw)
            time.sleep(0.01)
            GPIO.output(int(config["GPIO"]["VOL_DW"]), up)
            time.sleep(0.01)
            state["VOLUME"] = state["VOLUME"] + 1
    elif count < 0:
        for x in range(count, 0):
            up = operator.not_(up)
            dw = operator.not_(dw)
            GPIO.output(int(config["GPIO"]["VOL_DW"]), dw)
            time.sleep(0.01)
            GPIO.output(int(config["GPIO"]["VOL_UP"]), up)
            time.sleep(0.01)
            state["VOLUME"] = state["VOLUME"] - 1

    GPIO.setup(int(config["GPIO"]["VOL_UP"]), GPIO.IN)
    GPIO.setup(int(config["GPIO"]["VOL_DW"]), GPIO.IN)
    time.sleep(0.01)
    GPIO.add_event_detect(
        int(config["GPIO"]["VOL_UP"]), GPIO.BOTH, callback=speaker_volume
    )
    GPIO.add_event_detect(
        int(config["GPIO"]["VOL_DW"]), GPIO.BOTH, callback=speaker_volume
    )

    client.publish(
        config["MQTT"]["TOPIC"] + "/stat/VOLUME",
        str(state["VOLUME"]),
        int(config["MQTT"]["QOS"]),
    )
    client.publish(
        config["MQTT"]["TOPIC"] + "/stat/RESULT",
        '{ "VOLUME":"' + str(state["VOLUME"]) + '"}',
        int(config["MQTT"]["QOS"]),
    )


def speaker_init():
    # Use GPIO numbers not pin numbers
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(int(config["GPIO"]["POWER"]), GPIO.IN)
    GPIO.setup(int(config["GPIO"]["VOL_UP"]), GPIO.IN)
    GPIO.setup(int(config["GPIO"]["VOL_DW"]), GPIO.IN)
    GPIO.setup(int(config["GPIO"]["BT_LED"]), GPIO.IN)
    GPIO.setup(int(config["GPIO"]["AUX_LED"]), GPIO.IN)
    GPIO.add_event_detect(
        int(config["GPIO"]["AUX_LED"]), GPIO.BOTH, callback=speaker_power
    )
    GPIO.add_event_detect(
        int(config["GPIO"]["VOL_UP"]), GPIO.BOTH, callback=speaker_volume
    )
    GPIO.add_event_detect(
        int(config["GPIO"]["VOL_DW"]), GPIO.BOTH, callback=speaker_volume
    )

    if GPIO.input(int(config["GPIO"]["AUX_LED"])):
        state["POWER"] = "ON"
        set_volume(0 - int(config["VOLUME"]["MAXIMUM"]))
        set_volume(int(config["VOLUME"]["INITIAL"]))
    else:
        state["POWER"] = "OFF"
        state["VOLUME"] = int(config["VOLUME"]["INITIAL"])

    # Subscribe for cmnd events
    client.subscribe(config["MQTT"]["TOPIC"] + "/cmnd/+", int(config["MQTT"]["QOS"]))

    speaker_tele(1)

    # Subscribe for Home Assistant birth messages
    if config["MQTT"]["BIRTH_TOPIC"]:
        client.subscribe(config["MQTT"]["BIRTH_TOPIC"])


def speaker_power(channel):
    global lock
    with lock:
        if GPIO.input(int(config["GPIO"]["AUX_LED"])) and state["POWER"] == "OFF":
            logger.info("Speaker power state changed: ON")
            state["POWER"] = "ON"
            temp = state["VOLUME"] - int(config["VOLUME"]["DEFAULT"])
            state["VOLUME"] = int(config["VOLUME"]["DEFAULT"])
            time.sleep(3)
            set_volume(temp)
            time.sleep(0.5)
        elif not GPIO.input(int(config["GPIO"]["AUX_LED"])) and state["POWER"] == "ON":
            logger.info("Speaker power state changed: OFF")
            state["POWER"] = "OFF"
        else:
            return False
        client.publish(
            config["MQTT"]["TOPIC"] + "/stat/POWER",
            str(state["POWER"]),
            int(config["MQTT"]["QOS"]),
        )
        client.publish(
            config["MQTT"]["TOPIC"] + "/stat/RESULT",
            '{ "POWER":"' + str(state["POWER"]) + '"}',
            int(config["MQTT"]["QOS"]),
        )
        speaker_tele(1)


def speaker_volume(channel):
    global lock
    if state["POWER"] == "ON":
        with lock:
            up = GPIO.input(int(config["GPIO"]["VOL_UP"]))
            dw = GPIO.input(int(config["GPIO"]["VOL_DW"]))

            if up == dw:
                if channel != int(config["GPIO"]["VOL_UP"]) and state["VOLUME"] < int(
                    config["VOLUME"]["MAXIMUM"]
                ):
                    logger.info("Speaker volume changed: +")
                    state["VOLUME"] = state["VOLUME"] + 1
                elif channel != int(config["GPIO"]["VOL_DW"]) and state["VOLUME"] > 0:
                    logger.info("Speaker volume changed: -")
                    state["VOLUME"] = state["VOLUME"] - 1
                else:
                    return False
                client.publish(
                    config["MQTT"]["TOPIC"] + "/stat/VOLUME",
                    str(state["VOLUME"]),
                    int(config["MQTT"]["QOS"]),
                )
                client.publish(
                    config["MQTT"]["TOPIC"] + "/stat/RESULT",
                    '{ "VOLUME":"' + str(state["VOLUME"]) + '"}',
                    int(config["MQTT"]["QOS"]),
                )
                speaker_tele(1)


def speaker_tele(mode):
    global last_tele
    now = time.time()

    if now - last_tele > int(config["RUNTIME"]["TELE_INTERVAL"]) or mode == 1:
        # Sent LWT update
        client.publish(
            config["MQTT"]["TOPIC"] + "/tele/LWT", payload="Online", qos=0, retain=True
        )

        get_time()
        client.publish(
            config["MQTT"]["TOPIC"] + "/tele/STATE",
            json.dumps(state),
            int(config["MQTT"]["QOS"]),
        )
        last_tele = now
        return True
    else:
        return False


def get_time():
    result = ""
    time = uptime.uptime()
    result = "%01d" % int(time / 86400)
    time = time % 86400
    result = result + "T" + "%02d" % (int(time / 3600))
    time = time % 3600
    state["Uptime"] = (
        result + ":" + "%02d" % (int(time / 60)) + ":" + "%02d" % (time % 60)
    )
    state["Time"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def mqtt_init() -> None:
    global client

    # Create mqtt client
    client = mqtt.Client()
    # Register LWT message
    client.will_set(
        config["MQTT"]["TOPIC"] + "/tele/LWT", payload="Offline", qos=0, retain=True
    )
    # Register connect callback
    client.on_connect = mqtt_on_connect
    # Register disconnect callback
    client.on_disconnect = mqtt_on_disconnect
    # Register publish message callback
    client.on_message = mqtt_on_message
    # Set access token
    client.username_pw_set(config["MQTT"]["USER"], config["MQTT"]["PASS"])
    # Run receive thread
    client.loop_start()
    # Connect to broker
    client.connect(
        config["MQTT"]["SERVER"],
        int(config["MQTT"]["PORT"]),
        int(config["MQTT"]["TIMEOUT"]),
    )

    timeout = 0
    reconnect = 0
    time.sleep(1)
    while not client.is_connected():
        time.sleep(1)
        timeout += 1
        if timeout > 15:
            logger.info("MQTT waiting to connect")
            if reconnect > 10:
                logger.error("MQTT not connected!")
                raise MqttError("MQTT not connected!")
            client.reconnect()
            reconnect += 1
            timeout = 0


def mqtt_cleanup() -> None:
    global client

    if client:
        client.loop_stop()
        if client.is_connected():
            # Sent LWT update
            client.publish(
                config["MQTT"]["TOPIC"] + "/tele/LWT",
                payload="Offline",
                qos=0,
                retain=True,
            )
            client.disconnect()
        client = None


def mqtt_on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
    if rc != 0:
        logger.error("MQTT unexpected connect return code " + str(rc))
    else:
        logger.info("MQTT client connected")
        client.connected_flag = 1


def mqtt_on_disconnect(client: mqtt.Client, userdata: Any, rc: int) -> None:
    client.connected_flag = 0
    if rc != 0:
        logger.error("MQTT unexpected disconnect return code " + str(rc))
    logger.info("MQTT client disconnected")


# The callback for when a PUBLISH message is received from the server.
def mqtt_on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    global lock
    topic = str(msg.topic)
    payload = str(msg.payload.decode("utf-8"))

    tele = re.match(
        r"^" + config["MQTT"]["TOPIC"] + "\/cmnd\/(state|POWER|VOLUME)$", topic
    )
    birth = re.match(r"^" + config["MQTT"]["BIRTH_TOPIC"] + "$", topic)

    if tele:
        topic = tele.group(1)
        if topic == "state" and payload == "":
            speaker_tele(1)
        elif topic == "POWER":
            if payload == "":
                logger.info("get Speaker power")
                client.publish(
                    config["MQTT"]["TOPIC"] + "/stat/POWER",
                    str(state["POWER"]),
                    int(config["MQTT"]["QOS"]),
                )
            elif re.match(r"^ON|OFF$", payload):
                with lock:
                    set_power(payload)
            speaker_tele(1)
        elif topic == "VOLUME":
            if payload == "":
                logger.info("get Speaker volume")
                client.publish(
                    config["MQTT"]["TOPIC"] + "/stat/VOLUME",
                    str(state["VOLUME"]),
                    int(config["MQTT"]["QOS"]),
                )
            elif re.match(r"^\d+$", payload):
                with lock:
                    set_volume(int(payload) - state["VOLUME"])
            speaker_tele(1)
        else:
            logger.warning("Unknown topic: " + topic + ", message: " + payload)
    elif birth:
        if config["MQTT"]["BIRTH_TOPIC"]:
            if payload.lower() == "online":
                logger.info("Home Assistant is online")
                speaker_tele(1)
            else:
                logger.info("Home Assistant is " + payload)
    else:
        logger.warning("Unknown topic: " + topic + ", message: " + payload)


client = None
restart = 0
lock = Lock()
while True:
    try:
        # Init counters
        last_tele = 0
        # Create mqtt client
        if not client:
            # Init mqtt
            mqtt_init()
        # Init speaker
        speaker_init()
        # Run sending thread
        while True:
            speaker_tele(0)
            time.sleep(1)
    except BaseException as error:
        logger.error(f"An exception occurred: {type(error).__name__} – {error}")
        if type(error) in [MqttError, AppError] and (
            int(config["RUNTIME"]["MAX_ERROR"]) == 0
            or restart <= int(config["RUNTIME"]["MAX_ERROR"])
        ):
            if type(error) == MqttError:
                mqtt_cleanup()
            elif type(error) == AppError:
                pass
            restart += 1
            # Try to reconnect later
            time.sleep(int(config["RUNTIME"]["RESTART_DELAY"]))
        elif type(error) in [KeyboardInterrupt, SystemExit]:
            # Graceful shutdown
            logger.error("Gracefully terminating application")
            mqtt_cleanup()
            logger.error("Application terminated")
            sys.exit(0)
        else:
            # Exit with error
            logger.error(f"Unknown exception, aborting application")
            logger.debug(f"Exception details: {traceback.format_exc()}")
            sys.exit(1)

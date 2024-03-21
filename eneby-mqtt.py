#! /usr/bin/python

from threading import Lock
import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO
import configparser
import operator
import json
import time 
import uptime
import datetime
import re
import os
import sys

# define user-defined exception
class AppError(Exception):
    "Raised on aplication error"
    pass

class MqttConnect(Exception):
    "Raised on MQTT connection failure"
    pass

# global variables
state = { "POWER": "OFF", "VOLUME": 0, "Time": 0, "Uptime": 0 }

# read config
config = configparser.ConfigParser()
config.read('config.ini')
if 'MQTT' in config:
    for key in [ 'TOPIC', 'SERVER', 'PORT', 'QOS', 'TIMEOUT', 'USER', 'PASS']:
        if not config['MQTT'][key]:
            raise AppError("Missing or empty config entry MQTT/" + key)
else:
    raise AppError("Missing config section MQTT")  

if 'GPIO' in config:
    for key in [ 'POWER', 'VOL_UP', 'VOL_DW', 'BT_LED', 'AUX_LED']:
        if not config['GPIO'][key]:
            raise AppError("Missing or empty config entry GPIO/" + key)
else:
    raise AppError("Missing config section GPIO")

if 'VOLUME' in config:
    for key in [ 'MAXIMUM', 'DEFAULT', 'INITIAL']:
        if not config['VOLUME'][key]:
            raise AppError("Missing or empty config entry VOLUME/" + key)
else:
    raise AppError("Missing config section VOLUME")

if 'RUNTIME' in config:
    for key in [ 'MAX_ERROR', 'STATE_FILE']:
        if not config['RUNTIME'][key]:
            raise AppError("Missing or empty config entry RUNTIME/" + key)
else:
    raise AppError("Missing config section VOLUME")


def set_power(state):
    if state == "ON" and not GPIO.input(int(config['GPIO']['AUX_LED'])):
        print("Sent power " + state)
        GPIO.setup(int(config['GPIO']['POWER']), GPIO.OUT, initial = GPIO.LOW)
        time.sleep(0.1)
        GPIO.setup(int(config['GPIO']['POWER']), GPIO.IN)
    elif state == "OFF" and GPIO.input(int(config['GPIO']['AUX_LED'])):
        print("Sent power " + state)
        GPIO.setup(int(config['GPIO']['POWER']), GPIO.OUT, initial = GPIO.LOW)
        time.sleep(0.1)
        GPIO.setup(int(config['GPIO']['POWER']), GPIO.IN)


def set_volume(count = 0):
    if count > 0:
        if state["VOLUME"] == int(config['VOLUME']['MAXIMUM']):
            return True
        elif count > int(config['VOLUME']['MAXIMUM']) - state["VOLUME"]:
            count = int(config['VOLUME']['MAXIMUM']) - state["VOLUME"]
        print("Sent volume +" + str(count))
    elif count < 0:
        if state["VOLUME"] == 0:
            return True
        elif count < 0 - state["VOLUME"]:
            count = 0 - state["VOLUME"]
        print("Sent volume " + str(count))
    else:
        return True;

    up = GPIO.input(int(config['GPIO']['VOL_UP']))
    dw = GPIO.input(int(config['GPIO']['VOL_DW']))

    if up and dw:
        GPIO.remove_event_detect(int(config['GPIO']['VOL_UP']))
        GPIO.remove_event_detect(int(config['GPIO']['VOL_DW']))
        time.sleep(0.01)
        GPIO.setup(int(config['GPIO']['VOL_UP']), GPIO.OUT, initial = GPIO.LOW)
        time.sleep(0.01)
        GPIO.setup(int(config['GPIO']['VOL_DW']), GPIO.OUT, initial = GPIO.LOW)
        time.sleep(0.01)
    elif not up and not dw:
        GPIO.remove_event_detect(int(config['GPIO']['VOL_UP']))
        GPIO.remove_event_detect(int(config['GPIO']['VOL_DW']))
        time.sleep(0.01)
        GPIO.setup(int(config['GPIO']['VOL_UP']), GPIO.OUT, initial = GPIO.HIGH)
        time.sleep(0.01)
        GPIO.setup(int(config['GPIO']['VOL_DW']), GPIO.OUT, initial = GPIO.HIGH)
        time.sleep(0.01)
    else:
        print("invalid encoder status")
        return False

    if count > 0:
        for x in range(0, count):
            up = operator.not_(up)
            dw = operator.not_(dw)
            GPIO.output(int(config['GPIO']['VOL_UP']), dw)
            time.sleep(0.01)
            GPIO.output(int(config['GPIO']['VOL_DW']), up)
            time.sleep(0.01)
            state["VOLUME"] = state["VOLUME"] + 1
    elif count < 0:
        for x in range(count, 0):
            up = operator.not_(up)
            dw = operator.not_(dw)
            GPIO.output(int(config['GPIO']['VOL_DW']), dw)
            time.sleep(0.01)
            GPIO.output(int(config['GPIO']['VOL_UP']), up)
            time.sleep(0.01)
            state["VOLUME"] = state["VOLUME"] - 1

    GPIO.setup(int(config['GPIO']['VOL_UP']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['VOL_DW']), GPIO.IN)
    time.sleep(0.01)
    GPIO.add_event_detect(int(config['GPIO']['VOL_UP']), GPIO.BOTH, callback=speaker_volume)
    GPIO.add_event_detect(int(config['GPIO']['VOL_DW']), GPIO.BOTH, callback=speaker_volume)

    client.publish(config['MQTT']['TOPIC'] + '/stat/VOLUME', str(state["VOLUME"]), int(config['MQTT']['QOS']))
    client.publish(config['MQTT']['TOPIC'] + '/stat/RESULT', '{ "VOLUME":"' + str(state["VOLUME"]) + '"}', int(config['MQTT']['QOS']))


def speaker_init():
    # Use GPIO numbers not pin numbers
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(int(config['GPIO']['POWER']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['VOL_UP']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['VOL_DW']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['BT_LED']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['AUX_LED']), GPIO.IN)
    GPIO.add_event_detect(int(config['GPIO']['AUX_LED']), GPIO.BOTH, callback=speaker_power)
    GPIO.add_event_detect(int(config['GPIO']['VOL_UP']), GPIO.BOTH, callback=speaker_volume)
    GPIO.add_event_detect(int(config['GPIO']['VOL_DW']), GPIO.BOTH, callback=speaker_volume)

    if GPIO.input(int(config['GPIO']['AUX_LED'])):
        state["POWER"] = "ON"
        set_volume(0 - int(config['VOLUME']['MAXIMUM']))
        set_volume(int(config['VOLUME']['INITIAL']))
    else:
       state["POWER"] = "OFF"
       state["VOLUME"] = int(config['VOLUME']['INITIAL'])

    # Subscribe for cmnd events
    client.subscribe(config['MQTT']['TOPIC'] + '/cmnd/+', int(config['MQTT']['QOS']))


def speaker_power(channel):
    global lock
    with lock:
        if GPIO.input(int(config['GPIO']['AUX_LED'])) and state["POWER"] == "OFF":
            print("Speaker power state changed: ON")
            state["POWER"] = "ON"
            temp = state["VOLUME"] - int(config['VOLUME']['DEFAULT'])
            state["VOLUME"] = int(config['VOLUME']['DEFAULT'])
            time.sleep(3)
            set_volume(temp)
            time.sleep(0.5)
        elif not GPIO.input(int(config['GPIO']['AUX_LED'])) and state["POWER"] == "ON":
            print("Speaker power state changed: OFF")
            state["POWER"] = "OFF"
        else:
            return False
        client.publish(config['MQTT']['TOPIC'] + '/stat/POWER', str(state["POWER"]), int(config['MQTT']['QOS']))
        client.publish(config['MQTT']['TOPIC'] + '/stat/RESULT', '{ "POWER":"' + str(state["POWER"]) + '"}', int(config['MQTT']['QOS']))
        speaker_tele(1)


def speaker_volume(channel):
    global lock
    if state["POWER"] == "ON":
        with lock:
            up = GPIO.input(int(config['GPIO']['VOL_UP']))
            dw = GPIO.input(int(config['GPIO']['VOL_DW']))
           
            if up == dw:
                if channel != int(config['GPIO']['VOL_UP']) and state["VOLUME"] < int(config['VOLUME']['MAXIMUM']):
                    print("Speaker volume changed: +")
                    state["VOLUME"] = state["VOLUME"] + 1
                elif channel != int(config['GPIO']['VOL_DW']) and state["VOLUME"] > 0:
                    print("Speaker volume changed: -")
                    state["VOLUME"] = state["VOLUME"] - 1
                else:
                    return False
                client.publish(config['MQTT']['TOPIC'] + '/stat/VOLUME', str(state["VOLUME"]), int(config['MQTT']['QOS']))
                client.publish(config['MQTT']['TOPIC'] + '/stat/RESULT', '{ "VOLUME":"' + str(state["VOLUME"]) + '"}', int(config['MQTT']['QOS']))
                speaker_tele(1)


def speaker_tele(mode):
    global lasttele
    now = time.time()
    if mode or now - lasttele > 300:
        get_time()
        client.publish(config['MQTT']['TOPIC'] + '/tele/STATE', json.dumps(state), int(config['MQTT']['QOS']))
        lasttele = now


def get_time():
    result = ""
    time = uptime.uptime()
    result = "%01d" % int(time / 86400)
    time = time % 86400
    result = result + "T" + "%02d" % (int(time / 3600))
    time = time % 3600
    state["Uptime"] = result + ":" + "%02d" % (int(time / 60)) + ":" + "%02d" % (time % 60)
    state["Time"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    if rc != 0:
        print("MQTT unexpected connect return code " + str(rc))
    else:
        print("MQTT client connected")
        client.connected_flag = 1


def on_disconnect(client, userdata, rc):
    client.connected_flag = 0
    if rc != 0:
        print("MQTT unexpected disconnect return code " + str(rc))
    print("MQTT client disconnected")


# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    global lock
    topic = str(msg.topic)
    payload = str(msg.payload.decode("utf-8"))
    match = re.match(r'^' + config['MQTT']['TOPIC'] + '\/cmnd\/(state|POWER|VOLUME)$', topic)
    if match:
        topic = match.group(1)
        if topic == "state" and payload == "":
            speaker_tele(1)
        elif topic == "POWER":
            if payload == "":
                print("get Speaker power")
                client.publish(config['MQTT']['TOPIC'] + '/stat/POWER', str(state["POWER"]), int(config['MQTT']['QOS']))
            elif re.match(r'^ON|OFF$', payload):
                with lock:
                    set_power(payload)
            speaker_tele(1)
        elif topic == "VOLUME":
            if payload == "":
                print("get Speaker volume")
                client.publish(config['MQTT']['TOPIC'] + '/stat/VOLUME', str(state["VOLUME"]), int(config['MQTT']['QOS']))
            elif re.match(r'^\d+$', payload):
                with lock:
                    set_volume(int(payload) - volume)
            speaker_tele(1)
        else:
            print("Unknown topic: " + topic + ", message: " + payload)
    else:
        print("Unknown topic: " + topic + ", message: " + payload)


# touch state file on succesfull run
def state_file(mode):
    if mode:
        if int(config['RUNTIME']['MAX_ERROR']) > 0 and config['RUNTIME']['STATE_FILE']:
            with open(config['RUNTIME']['STATE_FILE'], 'a'):
                os.utime(config['RUNTIME']['STATE_FILE'], None)
    else:
        os.remove(config['RUNTIME']['STATE_FILE'])


# Add connection flags
mqtt.Client.connected_flag = 0
mqtt.Client.reconnect_count = 0

count = 0
lock = Lock()
while True:
    try:
        # Init counters
        lasttele = 0
        # Create mqtt client
        client = mqtt.Client()
        client.connected_flag = 0
        client.reconnect_count = 0
        # Register LWT message
        client.will_set(config['MQTT']['TOPIC'] + '/tele/LWT', payload="Offline", qos=0, retain=True)
        # Register connect callback
        client.on_connect = on_connect
        # Register disconnect callback
        client.on_disconnect = on_disconnect
        # Registed publish message callback
        client.on_message = on_message
        # Set access token
        client.username_pw_set(config['MQTT']['USER'], config['MQTT']['PASS'])
        # Run receive thread
        client.loop_start()
        # Connect to broker
        client.connect(config['MQTT']['SERVER'], int(config['MQTT']['PORT']), int(config['MQTT']['TIMEOUT']))
        time.sleep(1)
        while not client.connected_flag:
            print("MQTT waiting to connect")
            client.reconnect_count += 1
            if client.reconnect_count > 10:
                raise MqttConnect("MQTT restarting connection!")
            time.sleep(1)
        # Sent LWT update
        client.publish(config['MQTT']['TOPIC'] + '/tele/LWT',payload="Online", qos=0, retain=True)
        # Init speaker
        speaker_init()
        # Run sending thread
        while True:
            if client.connected_flag:
                count = 0
                speaker_tele(0)
                state_file(1)
            else:
                raise MqttConnect("MQTT connection lost!")
            time.sleep(1)
    except BaseException as error:
        print("An exception occurred:", type(error).__name__, "–", error)
        client.loop_stop()
        GPIO.cleanup()
        if client.connected_flag:
            client.unsubscribe(config['MQTT']['TOPIC'] + '/cmnd/+')
            client.disconnect()
        del client
        if type(error) in [ MqttConnect ] and count <= int(config['RUNTIME']['MAX_ERROR']):
            count = count + 1
            #Try to reconnect later
            time.sleep(10)
        elif type(error) in [ KeyboardInterrupt, SystemExit ]:
            state_file(0)
            # Gracefull shutwdown
            sys.exit(0)
        else:
            #Exit with error
            sys.exit(1)

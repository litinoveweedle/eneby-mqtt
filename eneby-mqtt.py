#! /usr/bin/python

import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO
import configparser
import operator
import json
import time 
import uptime
import datetime
import re

# global variables
speaker = { "POWER": 0, "VOLUME": 0, "Time": 0, "Uptime": 0 }

# read config
config = configparser.ConfigParser()
config.read('config.ini')
if 'MQTT' in config:
    for key in [ 'TOPIC', 'SERVER', 'PORT', 'QOS', 'TIMEOUT', 'USER', 'PASS']:
        if not config['MQTT'][key]:
            print("Missing or empty config entry MQTT/" + key)
            raise("Missing or empty config entry MQTT/" + key)
else:
    print("Missing config section MQTT")  
    raise("Missing config section MQTT")  

if 'GPIO' in config:
    for key in [ 'POWER', 'VOL_UP', 'VOL_DW', 'BT_LED', 'AUX_LED']:
        if not config['GPIO'][key]:
            print("Missing or empty config entry GPIO/" + key)
            raise("Missing or empty config entry GPIO/" + key)
else:
    print("Missing config section GPIO")
    raise("Missing config section GPIO")

if 'VOLUME' in config:
    for key in [ 'MAXIMUM', 'DEFAULT', 'INITIAL']:
        if not config['VOLUME'][key]:
            print("Missing or empty config entry VOLUME/" + key)
            raise("Missing or empty config entry VOLUME/" + key)
else:
    print("Missing config section VOLUME")
    raise("Missing config section VOLUME")


def set_power(state):
    if state and not GPIO.input(int(config['GPIO']['AUX_LED'])):
        print("Powering on")
        GPIO.remove_event_detect(int(config['GPIO']['AUX_LED']))
        GPIO.setup(int(config['GPIO']['POWER']), GPIO.OUT, initial = GPIO.LOW)
        time.sleep(0.5)
        GPIO.setup(int(config['GPIO']['POWER']), GPIO.IN)
        time.sleep(1)
        set_volume(volume - int(config['VOLUME']['DEFAULT']))
    elif not state and GPIO.input(int(config['GPIO']['AUX_LED'])):
        print("Powering off")
        GPIO.remove_event_detect(int(config['GPIO']['AUX_LED']))
        GPIO.setup(int(config['GPIO']['POWER']), GPIO.OUT, initial = GPIO.LOW)
        time.sleep(0.5)
        GPIO.setup(int(config['GPIO']['POWER']), GPIO.IN)
    else:
        speaker["POWER"] = state
        return True

    GPIO.add_event_detect(int(config['GPIO']['AUX_LED']), GPIO.BOTH, callback=speaker_power)
    speaker["POWER"] = state


def set_volume(count = 0):
    global up
    global dw
    global volume
    if count > 0:
        if volume == int(config['VOLUME']['MAXIMUM']):
            return True
        elif count > int(config['VOLUME']['MAXIMUM']) - volume:
            count = int(config['VOLUME']['MAXIMUM']) - volume
    elif count < 0:
        if volume == 0:
            return True
        elif count < 0 - volume:
            count = 0 - volume
    else:
        return True;

    if up and dw:
        GPIO.remove_event_detect(int(config['GPIO']['VOL_UP']))
        GPIO.remove_event_detect(int(config['GPIO']['VOL_DW']))
        GPIO.setup(int(config['GPIO']['VOL_UP']), GPIO.OUT, initial = GPIO.LOW)
        time.sleep(0.01)
        GPIO.setup(int(config['GPIO']['VOL_DW']), GPIO.OUT, initial = GPIO.LOW)
        time.sleep(0.01)
    elif not up and not dw:
        GPIO.remove_event_detect(int(config['GPIO']['VOL_UP']))
        GPIO.remove_event_detect(int(config['GPIO']['VOL_DW']))
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
            volume = volume + 1
    elif count < 0:
        for x in range(count, 0):
            up = operator.not_(up)
            dw = operator.not_(dw)
            GPIO.output(int(config['GPIO']['VOL_DW']), dw)
            time.sleep(0.01)
            GPIO.output(int(config['GPIO']['VOL_UP']), up)
            time.sleep(0.01)
            volume = volume - 1

    GPIO.setup(int(config['GPIO']['VOL_UP']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['VOL_DW']), GPIO.IN)
    time.sleep(0.01)
    GPIO.add_event_detect(int(config['GPIO']['VOL_UP']), GPIO.BOTH, callback=speaker_volume)
    GPIO.add_event_detect(int(config['GPIO']['VOL_DW']), GPIO.BOTH, callback=speaker_volume)

    speaker["VOLUME"] = volume


def speaker_init():
    global up
    global dw
    global volume

    # Use GPIO numbers not pin numbers
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(int(config['GPIO']['POWER']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['VOL_UP']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['VOL_DW']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['BT_LED']), GPIO.IN)
    GPIO.setup(int(config['GPIO']['AUX_LED']), GPIO.IN)

    up = GPIO.input(int(config['GPIO']['VOL_UP']))
    dw = GPIO.input(int(config['GPIO']['VOL_DW']))

    GPIO.add_event_detect(int(config['GPIO']['AUX_LED']), GPIO.BOTH, callback=speaker_power)
    if GPIO.input(int(config['GPIO']['AUX_LED'])):
        volume = int(config['VOLUME']['MAXIMUM'])
        set_volume(0 - int(config['VOLUME']['MAXIMUM']))
        set_volume(int(config['VOLUME']['INITIAL']))
    else:
        volume = int(config['VOLUME']['DEFAULT'])
        GPIO.add_event_detect(int(config['GPIO']['VOL_UP']), GPIO.BOTH, callback=speaker_volume)
        GPIO.add_event_detect(int(config['GPIO']['VOL_DW']), GPIO.BOTH, callback=speaker_volume)

    speaker["POWER"] = GPIO.input(int(config['GPIO']['AUX_LED']))
    speaker["VOLUME"] = volume


def speaker_state():
    return True


def speaker_power(channel):
    global volume

    if GPIO.input(int(config['GPIO']['AUX_LED'])):
        speaker["POWER"] = 1
        temp_volume = volume - int(config['VOLUME']['DEFAULT'])
        volume = int(config['VOLUME']['DEFAULT'])
        set_volume(temp_volume)
    else:
        speaker["POWER"] = 0

    client.publish(config['MQTT']['TOPIC'] + '/stat/RESULT', '{ "POWER":"' + str(speaker["POWER"]) + '"}', int(config['MQTT']['QOS']))
    client.publish(config['MQTT']['TOPIC'] + '/tele/STATE', json.dumps(speaker), int(config['MQTT']['QOS']))


def speaker_volume(channel):
    global up
    global dw
    global volume

    if up != dw:
        if channel != int(config['GPIO']['VOL_UP']):
            if volume < int(config['VOLUME']['MAXIMUM']):
                volume = volume + 1
        elif channel != int(config['GPIO']['VOL_DW']):
            if volume > 0:
                volume = volume - 1
        else:
            return False

    up = GPIO.input(int(config['GPIO']['VOL_UP']))
    dw = GPIO.input(int(config['GPIO']['VOL_DW']))
    if up == dw:
        speaker["VOLUME"] = volume
        client.publish(config['MQTT']['TOPIC'] + '/stat/RESULT', '{ "VOLUME":"' + str(speaker["VOLUME"]) + '"}', int(config['MQTT']['QOS']))
        client.publish(config['MQTT']['TOPIC'] + '/tele/STATE', json.dumps(speaker), int(config['MQTT']['QOS']))


def speaker_tele():
    global lasttele
    now = time.time()
    if now - lasttele > 300:
        get_time()
        client.publish(config['MQTT']['TOPIC'] + '/tele/STATE', json.dumps(speaker), int(config['MQTT']['QOS']))
        lasttele = now


def get_time():
    result = ""
    time = uptime.uptime()
    result = "%01d" % int(time / 86400)
    time = time % 86400
    result = result + "T" + "%02d" % (int(time / 3600))
    time = time % 3600
    speaker["Uptime"] = result + ":" + "%02d" % (int(time / 60)) + ":" + "%02d" % (time % 60)
    speaker["Time"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


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
    topic = str(msg.topic)
    payload = str(msg.payload.decode("utf-8"))
    match = re.match(r'^' + config['MQTT']['TOPIC'] + '\/cmnd\/(state|POWER|VOLUME)$', topic)
    if match:
        topic = match.group(1)
        if topic == "state" and payload == "":
            speaker_state()
        elif topic == "POWER":
            if payload == "":
                print("get Speaker power")
                client.publish(config['MQTT']['TOPIC'] + '/stat/POWER', str(speaker["POWER"]), int(config['MQTT']['QOS']))
            elif re.match(r'^([01])$', payload):
                print("set Speaker power: " + payload)
                set_power(int(payload))
                client.publish(config['MQTT']['TOPIC'] + '/stat/RESULT', '{ "POWER":"' + str(speaker["POWER"]) + '"}', int(config['MQTT']['QOS']))
                client.publish(config['MQTT']['TOPIC'] + '/tele/STATE', json.dumps(speaker), int(config['MQTT']['QOS']))
        elif topic == "VOLUME":
            if payload == "":
                print("get Speaker volume")
                client.publish(config['MQTT']['TOPIC'] + '/stat/VOLUME', str(speaker["VOLUME"]), int(config['MQTT']['QOS']))
            elif re.match(r'^\d+$', payload):
                print("set Speaker volume: " + payload)
                set_volume(int(payload) - volume)
                client.publish(config['MQTT']['TOPIC'] + '/stat/RESULT', '{ "VOLUME":"' + str(speaker["VOLUME"]) + '"}', int(config['MQTT']['QOS']))
                client.publish(config['MQTT']['TOPIC'] + '/tele/STATE', json.dumps(speaker), int(config['MQTT']['QOS']))
        else:
            print("Unknown topic: " + topic + ", message: " + payload)
        client.publish(config['MQTT']['TOPIC'] + '/tele/STATE', json.dumps(speaker), int(config['MQTT']['QOS']))
    else:
        print("Unknown topic: " + topic + ", message: " + payload)


# Add connection flags
mqtt.Client.connected_flag = 0
mqtt.Client.reconnect_count = 0

# Init speaker
speaker_init()
run = 1
while run:
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
                print("MQTT restarting connection!")
                raise("MQTT restarting connection!")
            time.sleep(1)
        # Sent LWT update
        client.publish(config['MQTT']['TOPIC'] + '/tele/LWT',payload="Online", qos=0, retain=True)
        # Subscribe for cmnd events
        client.subscribe(config['MQTT']['TOPIC'] + '/cmnd/+', int(config['MQTT']['QOS']))
        # Set default states
        speaker_state()
        # Run sending thread
        while True:
            if client.connected_flag:
                speaker_tele()
            else:
                print("MQTT connection lost!")
                raise("MQTT connection lost!")
            time.sleep(1)
    except KeyboardInterrupt:
        # Gracefull shutwdown
        run = 0
        client.loop_stop()
        if client.connected_flag:
            client.unsubscribe(config['MQTT']['TOPIC'] + '/cmnd/+')
            client.disconnect()
    except:
        client.loop_stop()
        if client.connected_flag:
            client.disconnect()
        del client
        time.sleep(5)

GPIO.cleanup()


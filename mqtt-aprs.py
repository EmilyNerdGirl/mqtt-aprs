#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

__author__ = "Mike Loebl"
__copyright__ = "Copyright (C) Mike Loebl"

# Script based on mqtt-owfs-temp written by Kyle Gordon and converted for use with APRS
# Source: https://github.com/kylegordon/mqtt-owfs-temp

import os
import logging
import signal
import socket
import time
import sys
import binascii

import paho.mqtt.client as paho
import ConfigParser

import setproctitle

import aprslib

from datetime import datetime, timedelta

# Read the config file
config = ConfigParser.RawConfigParser()
# TODO: Fix path: 
config.read("/etc/mqtt-aprs/mqtt-aprs.cfg")

# Use ConfigParser to pick out the settings
DEBUG = config.getboolean("global", "debug")
LOGFILE = config.get("global", "logfile")
MQTT_HOST = config.get("global", "mqtt_host")
MQTT_PORT = config.getint("global", "mqtt_port")
MQTT_SUBTOPIC = config.get("global", "MQTT_SUBTOPIC")
MQTT_TOPIC = "/raw/" + socket.getfqdn() + "/" + MQTT_SUBTOPIC
MQTT_USERNAME = config.get("global", "MQTT_USERNAME")
MQTT_PASSWORD = config.get("global", "MQTT_PASSWORD")
METRICUNITS = config.get("global", "METRICUNITS")

APRS_CALLSIGN = config.get("global", "APRS_CALLSIGN")
APRS_PASSWORD = config.get("global", "APRS_PASSWORD")
APRS_HOST = config.get("global", "APRS_HOST")
APRS_PORT = config.get("global", "APRS_PORT")
APRS_FILTER = config.get("global", "APRS_FILTER")
APRS_PROCESS = config.get("global", "APRS_PROCESS")

APRS_LATITUDE = config.get("global", "APRS_LATITUDE")
APRS_LONGITUDE = config.get("global", "APRS_LONGITUDE")

APPNAME = MQTT_SUBTOPIC
PRESENCETOPIC = "clients/" + socket.getfqdn() + "/" + APPNAME + "/state"
setproctitle.setproctitle(APPNAME)
client_id = APPNAME + "_%d" % os.getpid()

mqttc = paho.Client()

LOGFORMAT = '%(asctime)-15s %(message)s'

if DEBUG:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.DEBUG,
                        format=LOGFORMAT)
else:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.INFO,
                        format=LOGFORMAT)

logging.info("Starting " + APPNAME)
logging.info("INFO MODE")
logging.debug("DEBUG MODE")

def celsiusCon(farenheit):
    return (farenheit - 32)*(5/9)
def farenheitCon(celsius):
    return ((celsius*(9/5)) + 32)

# All the MQTT callbacks start here


def on_publish(mosq, obj, mid):
    """
    What to do when a message is published
    """
    logging.debug("MID " + str(mid) + " published.")


def on_subscribe(mosq, obj, mid, qos_list):
    """
    What to do in the event of subscribing to a topic"
    """
    logging.debug("Subscribe with mid " + str(mid) + " received.")


def on_unsubscribe(mosq, obj, mid):
    """
    What to do in the event of unsubscribing from a topic
    """
    logging.debug("Unsubscribe with mid " + str(mid) + " received.")


def on_connect(self, mosq, obj, result_code):
    """
    Handle connections (or failures) to the broker.
    This is called after the client has received a CONNACK message
    from the broker in response to calling connect().
    The parameter rc is an integer giving the return code:
    0: Success
    1: Refused – unacceptable protocol version
    2: Refused – identifier rejected
    3: Refused – server unavailable
    4: Refused – bad user name or password (MQTT v3.1 broker only)
    5: Refused – not authorised (MQTT v3.1 broker only)
    """
    logging.debug("on_connect RC: " + str(result_code))
    if result_code == 0:
        logging.info("Connected to %s:%s", MQTT_HOST, MQTT_PORT)
        # Publish retained LWT as per
        # http://stackoverflow.com/q/97694
        # See also the will_set function in connect() below
        mqttc.publish(PRESENCETOPIC, "1", retain=True)
        process_connection()
    elif result_code == 1:
        logging.info("Connection refused - unacceptable protocol version")
        cleanup()
    elif result_code == 2:
        logging.info("Connection refused - identifier rejected")
        cleanup()
    elif result_code == 3:
        logging.info("Connection refused - server unavailable")
        logging.info("Retrying in 30 seconds")
        time.sleep(30)
    elif result_code == 4:
        logging.info("Connection refused - bad user name or password")
        cleanup()
    elif result_code == 5:
        logging.info("Connection refused - not authorised")
        cleanup()
    else:
        logging.warning("Something went wrong. RC:" + str(result_code))
        cleanup()


def on_disconnect(mosq, obj, result_code):
    """
    Handle disconnections from the broker
    """
    if result_code == 0:
        logging.info("Clean disconnection")
    else:
        logging.info("Unexpected disconnection! Reconnecting in 5 seconds")
        logging.debug("Result code: %s", result_code)
        time.sleep(5)


def on_message(mosq, obj, msg):
    """
    What to do when the client recieves a message from the broker
    """
    logging.debug("Received: " + msg.payload +
                  " received on topic " + msg.topic +
                  " with QoS " + str(msg.qos))
    process_message(msg)


def on_log(mosq, obj, level, string):
    """
    What to do with debug log output from the MQTT library
    """
    logging.debug(string)

# End of MQTT callbacks


def cleanup(signum, frame):
    """
    Signal handler to ensure we disconnect cleanly
    in the event of a SIGTERM or SIGINT.
    """
    logging.info("Disconnecting from broker")
    # Publish a retained message to state that this client is offline
    mqttc.publish(PRESENCETOPIC, "0", retain=True)
    mqttc.disconnect()
    mqttc.loop_stop()
    logging.info("Exiting on signal %d", signum)
    sys.exit(signum)

def connect():
    """
    Connect to the broker, define the callbacks, and subscribe
    This will also set the Last Will and Testament (LWT)
    The LWT will be published in the event of an unclean or
    unexpected disconnection.
    """
    logging.info("Connecting to %s:%s", MQTT_HOST, MQTT_PORT)

    if MQTT_USERNAME:
        logging.info("Found username %s", MQTT_USERNAME)
        mqttc.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    # Set the Last Will and Testament (LWT) *before* connecting
    mqttc.will_set(PRESENCETOPIC, "0", qos=0, retain=True)
    result = mqttc.connect(MQTT_HOST, MQTT_PORT, 60)
    if result != 0:
        logging.info("Connection failed with error code %s. Retrying", result)
        
        time.sleep(10)
        connect()

    # Define the callbacks
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_publish = on_publish
    mqttc.on_subscribe = on_subscribe
    mqttc.on_unsubscribe = on_unsubscribe
    mqttc.on_message = on_message
    if DEBUG:
        mqttc.on_log = on_log

    mqttc.loop_start()

def process_connection():
    """
    What to do when a new connection is established
    """
    logging.debug("Processing connection")


def process_message(mosq, obj, msg):
    """
    What to do with the message that's arrived
    """
    logging.debug("Received: %s", msg.topic)


def find_in_sublists(lst, value):
    for sub_i, sublist in enumerate(lst):
        try:
            return (sub_i, sublist.index(value))
        except ValueError:
            pass

    raise ValueError("%s is not in lists" % value)

def callback(packet):
    logging.debug("Raw Packet: %s", packet)

    if APRS_PROCESS == "True":
        aprspacket = aprs._parse(packet)

        ssid = aprspacket.get('from', None)
        logging.debug("SSID: %s", ssid)


        rawpacket = aprspacket.get('raw', None)
        logging.debug("RAW: %s",  rawpacket)
        publish_aprstomqtt(ssid, "raw", rawpacket)

        aprspath = aprspacket.get('path', None)
        if aprspath:
            logging.debug("path: %s", aprspath)
            publish_aprstomqtt(ssid, "path",aprspath)


        packet_format = aprspacket.get('format', None)
        logging.debug("format: %s",  packet_format)
        publish_aprstomqtt(ssid, "format", packet_format)
        
        symbol_table = aprspacket.get('symbol_table', None)
        symbol = aprspacket.get('symbol', None)
        
        if symbol_table and symbol:
            icon = symbol_table + symbol
            logging.debug("icon: %s", icon)
            publish_aprstomqtt(ssid, "icon", icon)

        aprs_lat = aprspacket.get('latitude', None)
        aprs_lon = aprspacket.get('longitude', None)
        if aprs_lat and aprs_lon:
            aprs_lat = round(aprs_lat, 4)
            aprs_lon = round(aprs_lon, 4)
            logging.debug("latitude: %s",  aprs_lat)
            logging.debug("longitude: %s",  aprs_lon)
            distance = get_distance(aprs_lat, aprs_lon)
            publish_aprstomqtt(ssid, "latitude", aprs_lat)
            publish_aprstomqtt(ssid, "longitude",aprs_lon)

            logging.debug("Distance away: %s", distance)
            publish_aprstomqtt(ssid, "distance",distance)

        altitude = aprspacket.get('altitude', None)
        if altitude:
            if METRICUNITS is "0":
                altitude = altitude / 0.3048
            logging.debug("altitude: %s", altitude)
            publish_aprstomqtt(ssid, "altitude",altitude)

        comment = aprspacket.get('comment', None)
        if comment:
            logging.debug("comment: %s", comment)
            publish_aprstomqtt(ssid, "comment",comment)

        telemetry = aprspacket.get('telemetry', None)
        if telemetry:
            logging.debug("telemetry: %s", telemetry)
            publish_aprstomqtt(ssid, "telemetry",telemetry)
            
        message = aprspacket.get('message_text', None)
        if message:
            logging.debug("message: %s", message)
            publish_aprstomqtt(ssid, "message",message)
    else:
        publish_aprstomqtt_nossid(packet)    


def publish_aprstomqtt(inssid, inname, invalue):
    topic_path = MQTT_TOPIC + "/" + inssid + "/" + inname
    logging.debug("Publishing topic: %s with value %s" % (topic_path, invalue))
    mqttc.publish(topic_path, unicode(invalue).encode('utf-8').strip())

def publish_aprstomqtt_nossid(invalue):
    topic_path = MQTT_TOPIC
    logging.debug("Publishing topic: %s with value %s" % (topic_path, invalue))
    mqttc.publish(topic_path, unicode(invalue).encode('utf-8').strip())


def get_distance(inlat, inlon):
    if APRS_LATITUDE and APRS_LONGITUDE:
        # From: https://stackoverflow.com/questions/19412462/getting-distance-between-two-points-based-on-latitude-longitude
        # approximate radius of earth in km
        R = 6373.0

        from math import sin, cos, sqrt, atan2, radians    
        lat1 = radians(float(APRS_LATITUDE))
        lon1 = radians(float(APRS_LONGITUDE))
        lat2 = radians(float(inlat))
        lon2 = radians(float(inlon))

        dlon = lon2 - lon1
        dlat = lat2 - lat1

        a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        distance = R  * c

        if METRICUNITS is "0":
            distance = distance * 0.621371
                
        return round(distance, 2)

def aprs_connect():


    # Listen for specific packet
    aprs.set_filter(APRS_FILTER)

    # Open the APRS connection to the server  
    aprs.connect(blocking=True)

    logging.debug("APRS Processing: %s", APRS_PROCESS)
    # Set a callback for when a packet is received
    if APRS_PROCESS == "True":
        aprs.consumer(callback, raw=True)
    else:
        aprs.consumer(callback)


  

                    
# Use the signal module to handle signals
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)
try:
    # Prepare the APRS connection
    aprs = aprslib.IS(APRS_CALLSIGN,
                    passwd=APRS_PASSWORD,
                    host=APRS_HOST,
                    port=APRS_PORT,
                    skip_login=False)

# Connect to the broker and enter the main loop
    connect()
    aprs_connect()

except KeyboardInterrupt:
    logging.info("Interrupted by keypress")
    sys.exit(0)
except aprslib.exceptions.ConnectionDrop:
    logging.info("Connection to APRS server dropped, trying again in 30 seconds...")
    time.sleep(30)
    aprs_connect
except aprslib.exceptions.ConnectionError:
    logging.info("Connection to APRS server failed, trying again in 30 seconds...")
    time.sleep(30)
    aprs_connect    

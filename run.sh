#!/bin/sh
CONFIG_PATH=/data/options.json

# Read options; support `devices` (comma separated) or legacy `device`, and HA discovery flag
MQTT_SERVER="$(jq --raw-output '.mqtt_server' $CONFIG_PATH)" \
MQTT_USER="$(jq --raw-output '.mqtt_user' $CONFIG_PATH)" \
MQTT_PASS="$(jq --raw-output '.mqtt_pass' $CONFIG_PATH)" \
MQTT_CLIENT_ID="$(jq --raw-output '.mqtt_client_id' $CONFIG_PATH)" \
MQTT_TOPIC_PARALLEL="$(jq --raw-output '.mqtt_topic_parallel' $CONFIG_PATH)" \
MQTT_TOPIC_SETTINGS="$(jq --raw-output '.mqtt_topic_settings' $CONFIG_PATH)" \
MQTT_TOPIC="$(jq --raw-output '.mqtt_topic' $CONFIG_PATH)" \
DEVICES="$(jq --raw-output '.devices // .device' $CONFIG_PATH)" \
MQTT_HA_DISCOVERY="$(jq --raw-output '.mqtt_ha_discovery // false' $CONFIG_PATH)" \
python /monitor.py

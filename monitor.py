#! /usr/bin/python

# Axpert Inverter control script
# Multi-device support, Home Assistant MQTT discovery support

import time
import json
import os
import fcntl
import crcmod.predefined
from binascii import unhexlify
import paho.mqtt.client as mqtt
from random import randint
import threading
import glob

# mappings from original script
battery_types = {'0': 'AGM', '1': 'Flooded', '2': 'User'}
voltage_ranges = {'0': 'Appliance', '1': 'UPS'}
output_sources = {'0': 'utility', '1': 'solar', '2': 'battery'}
charger_sources = {'0': 'utility first', '1': 'solar first', '2': 'solar + utility', '3': 'solar only'}
machine_types = {'00': 'Grid tie', '01': 'Off Grid', '10': 'Hybrid'}
topologies = {'0': 'transformerless', '1': 'transformer'}
output_modes = {'0': 'single machine output', '1': 'parallel output', '2': 'Phase 1 of 3 Phase output', '3': 'Phase 2 of 3 Phase output', '4': 'Phase 3 of 3 Phase output'}
pv_ok_conditions = {'0': 'As long as one unit of inverters has connect PV, parallel system will consider PV OK', '1': 'Only All of inverters have connect PV, parallel system will consider PV OK'}
pv_power_balance = {'0': 'PV input max current will be the max charged current', '1': 'PV input max power will be the sum of the max charged power and loads power'}


class DeviceMonitor(threading.Thread):
    def __init__(self, device, client, topics, ha_discovery=False):
        super().__init__(daemon=True)
        self.device = device
        self.client = client
        self.topics = topics
        self.ha_discovery = ha_discovery
        self.announced = set()
        self.serial_number = None

    def serial_command(self, command):
        xmodem_crc_func = crcmod.predefined.mkCrcFun('xmodem')
        command_bytes = command.encode('utf-8')
        crc_hex = hex(xmodem_crc_func(command_bytes)).replace('0x', '')
        command_crc = command_bytes + unhexlify(crc_hex.encode('utf-8')) + b'\x0d'

        try:
            fd = os.open(self.device, os.O_RDWR | os.O_NOCTTY)
            # make non-blocking
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        except Exception as e:
            raise RuntimeError(f'error opening device {self.device}: {e}')

        try:
            os.write(fd, command_crc)

            response = b''
            timeout_counter = 0
            while b'\r' not in response:
                if timeout_counter > 500:
                    raise RuntimeError('Read operation timed out')
                timeout_counter += 1
                try:
                    chunk = os.read(fd, 256)
                    if chunk:
                        response += chunk
                except Exception:
                    time.sleep(0.01)
                if len(response) > 0 and (response[0] != ord('(') or b'NAKss' in response):
                    raise RuntimeError('NAKss')

            try:
                response = response.decode('utf-8')
            except UnicodeDecodeError:
                response = response.decode('iso-8859-1')

            response = response.rstrip()
            lastI = response.find('\r')
            parsed = response[1:lastI-2]
            return parsed
        finally:
            try:
                os.close(fd)
            except Exception:
                pass

    def get_parallel_data(self):
        try:
            response = self.serial_command('QPGS0')
            nums = response.split(' ')
            if len(nums) < 27:
                return None

            data = {}
            data['Gridmode'] = 1 if nums[2] == 'L' else 0
            data['SerialNumber'] = int(nums[1])
            data['BatteryChargingCurrent'] = int(nums[12])
            data['BatteryDischargeCurrent'] = int(nums[26])
            data['TotalChargingCurrent'] = int(nums[15])
            data['GridVoltage'] = float(nums[4])
            data['GridFrequency'] = float(nums[5])
            data['OutputVoltage'] = float(nums[6])
            data['OutputFrequency'] = float(nums[7])
            data['OutputAparentPower'] = int(nums[8])
            data['OutputActivePower'] = int(nums[9])
            data['LoadPercentage'] = int(nums[10])
            data['BatteryVoltage'] = float(nums[11])
            data['BatteryCapacity'] = float(nums[13])
            data['PvInputVoltage'] = float(nums[14])
            data['TotalAcOutputApparentPower'] = int(nums[16])
            data['TotalAcOutputActivePower'] = int(nums[17])
            data['TotalAcOutputPercentage'] = int(nums[18])
            data['OutputMode'] = int(nums[20])
            data['ChargerSourcePriority'] = int(nums[21])
            data['MaxChargeCurrent'] = int(nums[22])
            data['MaxChargerRange'] = int(nums[23])
            data['MaxAcChargerCurrent'] = int(nums[24])
            data['PvInputCurrentForBattery'] = int(nums[25])
            data['Solarmode'] = 1 if nums[2] == 'B' else 0
            return data
        except Exception as e:
            print('error parsing parallel data:', e)
            return None

    def get_data(self):
        try:
            response = self.serial_command('QPIGS')
            nums = response.split(' ')
            if len(nums) < 21:
                return None
            data = {}
            data['BusVoltage'] = float(nums[7])
            data['InverterHeatsinkTemperature'] = float(nums[11])
            data['BatteryVoltageFromScc'] = float(nums[14])
            data['PvInputCurrent'] = int(nums[12])
            data['PvInputVoltage'] = float(nums[13])
            data['PvInputPower'] = int(nums[19])
            data['BatteryChargingCurrent'] = int(nums[9])
            data['BatteryDischargeCurrent'] = int(nums[15])
            data['DeviceStatus'] = nums[16]
            return data
        except Exception as e:
            print('error parsing data:', e)
            return None

    def get_settings(self):
        try:
            response = self.serial_command('QPIRI')
            nums = response.split(' ')
            if len(nums) < 26:
                return None
            data = {}
            data['AcInputVoltage'] = float(nums[0])
            data['AcInputCurrent'] = float(nums[1])
            data['AcOutputVoltage'] = float(nums[2])
            data['AcOutputFrequency'] = float(nums[3])
            data['AcOutputCurrent'] = float(nums[4])
            data['AcOutputApparentPower'] = int(nums[5])
            data['AcOutputActivePower'] = int(nums[6])
            data['BatteryVoltage'] = float(nums[7])
            data['BatteryRechargeVoltage'] = float(nums[8])
            data['BatteryUnderVoltage'] = float(nums[9])
            data['BatteryBulkVoltage'] = float(nums[10])
            data['BatteryFloatVoltage'] = float(nums[11])
            data['BatteryType'] = battery_types.get(nums[12], nums[12])
            data['MaxAcChargingCurrent'] = int(nums[13])
            data['MaxChargingCurrent'] = int(nums[14])
            data['InputVoltageRange'] = voltage_ranges.get(nums[15], nums[15])
            data['OutputSourcePriority'] = output_sources.get(nums[16], nums[16])
            data['ChargerSourcePriority'] = charger_sources.get(nums[17], nums[17])
            data['MaxParallelUnits'] = int(nums[18])
            data['MachineType'] = machine_types.get(nums[19], nums[19])
            data['Topology'] = topologies.get(nums[20], nums[20])
            data['OutputMode'] = output_modes.get(nums[21], nums[21])
            data['BatteryRedischargeVoltage'] = float(nums[22])
            data['PvOkCondition'] = pv_ok_conditions.get(nums[23], nums[23])
            data['PvPowerBalance'] = pv_power_balance.get(nums[24], nums[24])
            data['MaxBatteryCvChargingTime'] = int(nums[25])
            return data
        except Exception as e:
            print('error parsing settings:', e)
            return None

    def publish_state(self, topic_template, payload_obj):
        if not topic_template:
            return
        topic = topic_template.replace('{sn}', str(self.serial_number)) if self.serial_number else topic_template
        payload = json.dumps(payload_obj)
        try:
            self.client.publish(topic, payload, qos=0, retain=True)
        except Exception as e:
            print('error publishing:', e)

    def announce_ha(self, state_topic, payload_obj):
        # Use Home Assistant discovery to create sensors that extract values from JSON
        if not self.ha_discovery:
            return
        for key in payload_obj.keys():
            if key in self.announced:
                continue
            metric = key
            unique = f'axpert_{self.serial_number}_{metric}'
            name = f'Axpert {self.serial_number} {metric}'
            discovery_topic = f'homeassistant/sensor/{unique}/config'
            config = {
                'name': name,
                'state_topic': state_topic,
                'value_template': '{{ value_json.%s }}' % metric,
                'unique_id': unique,
                'device': {'identifiers': [str(self.serial_number)], 'name': f'Axpert {self.serial_number}'}
            }
            try:
                self.client.publish(discovery_topic, json.dumps(config), qos=0, retain=True)
                self.announced.add(metric)
            except Exception as e:
                print('error announcing HA sensor:', e)

    def run(self):
        time.sleep(randint(0, 5))
        try:
            sn_resp = self.serial_command('QID')
            self.serial_number = sn_resp.strip()
        except Exception as e:
            print(f'Failed to read serial for {self.device}:', e)
            self.serial_number = os.path.basename(self.device)

        print('Reading from inverter', self.serial_number, 'on', self.device)

        while True:
            try:
                pdata = self.get_parallel_data()
                if pdata:
                    self.publish_state(self.topics.get('parallel'), pdata)
                    self.announce_ha(self.topics.get('parallel'), pdata)
                time.sleep(1)

                data = self.get_data()
                if data:
                    self.publish_state(self.topics.get('state'), data)
                    self.announce_ha(self.topics.get('state'), data)
                time.sleep(1)

                settings = self.get_settings()
                if settings:
                    self.publish_state(self.topics.get('settings'), settings)
                    self.announce_ha(self.topics.get('settings'), settings)
                time.sleep(4)
            except Exception as e:
                print('Error in device loop', self.device, e)
                time.sleep(10)


def find_devices_from_env():
    # DEVICES can be comma separated list, a single DEVICE, or AUTO to auto-detect common serials
    devs = os.environ.get('DEVICES') or os.environ.get('DEVICE')
    if not devs:
        return []
    if devs.upper() == 'AUTO':
        candidates = []
        for pattern in ['/dev/ttyUSB*', '/dev/ttyACM*', '/dev/hwn*', '/dev/serial/by-id/*']:
            candidates.extend(glob.glob(pattern))
        return sorted(set(candidates))
    return [d.strip() for d in devs.split(',') if d.strip()]


def main():
    # create single MQTT client used by threads (loop started)
    mqtt_id = os.environ.get('MQTT_CLIENT_ID', 'axpert-monitor')
    client = mqtt.Client(client_id=mqtt_id)
    if os.environ.get('MQTT_USER'):
        client.username_pw_set(os.environ.get('MQTT_USER'), os.environ.get('MQTT_PASS'))
    client.connect(os.environ.get('MQTT_SERVER', 'localhost'))
    client.loop_start()

    device_list = find_devices_from_env()
    if not device_list:
        print('No devices found. Set DEVICES or DEVICE or DEVICES=AUTO')
        return

    topics = {
        'state': os.environ.get('MQTT_TOPIC', 'axpert/{sn}/state'),
        'parallel': os.environ.get('MQTT_TOPIC_PARALLEL', 'axpert/{sn}/parallel'),
        'settings': os.environ.get('MQTT_TOPIC_SETTINGS', 'axpert/{sn}/settings')
    }

    ha_discovery = os.environ.get('MQTT_HA_DISCOVERY', '0') in ('1', 'true', 'True')

    monitors = []
    for dev in device_list:
        mon = DeviceMonitor(dev, client, topics, ha_discovery=ha_discovery)
        mon.start()
        monitors.append(mon)

    # keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print('Shutting down')


if __name__ == '__main__':
    main()
# -*- coding: utf-8 -*-
"""Bo dieu khien Smarthome chay tren Raspberry Pi 4."""

import argparse
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import adafruit_ads1x15.ads1115 as ADS
import adafruit_ahtx0
import board
import busio
import RPi.GPIO as GPIO
from adafruit_ads1x15.analog_in import AnalogIn
from RPLCD.i2c import CharLCD
from smbus2 import SMBus

try:
    # API moi cua adafruit-circuitpython-ads1x15.
    from adafruit_ads1x15.ads1x15 import Pin

    GAS_ADC_PIN = Pin.A0
except (ImportError, AttributeError):
    # Tuong thich voi cac ban cu con dat P0 trong module ads1115.
    GAS_ADC_PIN = getattr(ADS, "P0", 0)


# ========================= CAU HINH PHAN CUNG =========================
SERVO_PIN = 19
FAN_PIN = 20
FLAME_PIN = 16
WARNING_LED_PIN = 5
LIGHT_PIN = 8

LCD_ADDRESS = 0x21
ADS1115_ADDRESS = 0x49
RFID_ADDRESS = 0x2C

# Goc da hieu chinh cua cua: 0 do dong, 175 do mo.
CLOSE_ANGLE = 0.0
OPEN_ANGLE = 175.0
SERVO_MOVE_SECONDS = 0.7
RFID_OPEN_SECONDS = 5.0

# Cam bien gas co muc binh thuong khoang 1.1 V tren he thong hien tai.
# Gas canh bao: mo cua. Gas nguy hiem: mo cua va bat quat.
GAS_WARNING_V = 2.0
GAS_DANGER_V = 2.5
GAS_HYSTERESIS_V = 0.10

TEMP_THRESHOLD_C = 30.0
HUMIDITY_THRESHOLD = 80.0

LED_BLINK_SECONDS = 0.20
LCD_BLINK_SECONDS = 0.50
ENV_DISPLAY_SECONDS = 3.0
LIGHT_STABLE_READS = 3
LIGHT_DISPLAY_SECONDS = 3.0
FLAME_HOLD_SECONDS = 3.0
AI_STATUS_TIMEOUT_SECONDS = 1.5
NETWORK_INTERVAL_SECONDS = 0.15


class MFRC522I2C:
    """Driver RFID duoc giu theo luong cua file rfid.py."""

    OK = 1
    ERR = 0
    CommandReg, ComIEnReg, ComIrqReg = 0x01, 0x02, 0x04
    FIFODataReg, FIFOLevelReg = 0x09, 0x0A
    BitFramingReg = 0x0D
    ModeReg, TxControlReg, TxASKReg = 0x11, 0x14, 0x15
    VersionReg = 0x37

    def __init__(self, bus_num=1, address=RFID_ADDRESS):
        self.addr = address
        self.bus = SMBus(bus_num)
        try:
            self.bus.read_byte_data(self.addr, self.VersionReg)
        except OSError as exc:
            self.bus.close()
            raise RuntimeError(
                "Khong ket noi duoc RFID tai 0x%02X" % self.addr
            ) from exc
        self._init_device()

    def close(self):
        self.bus.close()

    def _write(self, register, value):
        self.bus.write_byte_data(self.addr, register, value)

    def _read(self, register):
        return self.bus.read_byte_data(self.addr, register)

    def _init_device(self):
        self._write(self.CommandReg, 0x0F)
        time.sleep(0.05)
        self._write(self.ModeReg, 0x3D)
        self._write(self.TxASKReg, 0x40)
        value = self._read(self.TxControlReg)
        if not value & 0x03:
            self._write(self.TxControlReg, value | 0x03)

    def _to_card(self, command, data):
        irq_enable = 0x77 if command == 0x0C else 0x00
        wait_irq = 0x30 if command == 0x0C else 0x00
        try:
            self._write(self.ComIEnReg, irq_enable | 0x80)
            self._write(self.ComIrqReg, self._read(self.ComIrqReg) & ~0x80)
            self._write(self.FIFOLevelReg, self._read(self.FIFOLevelReg) | 0x80)
            self._write(self.CommandReg, 0x00)
            for value in data:
                self._write(self.FIFODataReg, value)
            self._write(self.CommandReg, command)
            if command == 0x0C:
                self._write(
                    self.BitFramingReg,
                    self._read(self.BitFramingReg) | 0x80,
                )

            deadline = time.monotonic() + 0.10
            while time.monotonic() < deadline:
                irq = self._read(self.ComIrqReg)
                if irq & wait_irq:
                    break
                if irq & 0x01:
                    return self.ERR, []
            else:
                return self.ERR, []

            self._write(
                self.BitFramingReg,
                self._read(self.BitFramingReg) & ~0x80,
            )
            if self._read(0x06) & 0x1B:
                return self.ERR, []
            count = self._read(self.FIFOLevelReg)
            return self.OK, [self._read(self.FIFODataReg) for _ in range(count)]
        except OSError:
            return self.ERR, []

    def read_uid(self):
        try:
            self._write(self.BitFramingReg, 0x07)
            status, _ = self._to_card(0x0C, [0x26])
            if status != self.OK:
                return None
            self._write(self.BitFramingReg, 0x00)
            status, received = self._to_card(0x0C, [0x93, 0x20])
            if status == self.OK and len(received) >= 4:
                return ":".join("%02X" % value for value in received[:4])
        except OSError:
            return None
        return None


class Door:
    def __init__(self, pin):
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
        self.pwm = GPIO.PWM(pin, 50)
        self.pwm.start(0)
        self.is_open = None

    @staticmethod
    def _duty(angle):
        if not 0.0 <= angle <= 180.0:
            raise ValueError("Goc servo phai nam trong 0..180 do")
        return 2.5 + (angle / 180.0) * 10.0

    def set_open(self, should_open, force=False):
        if not force and should_open == self.is_open:
            return

        angle = OPEN_ANGLE if should_open else CLOSE_ANGLE
        self.pwm.ChangeDutyCycle(self._duty(angle))

        if should_open:
            # Giu xung khi cua mo de tai co khi khong keo cua dong lai.
            print("[CUA] MO - %.0f do" % angle, flush=True)
        else:
            print("[CUA] DONG - %.0f do" % angle, flush=True)
            time.sleep(SERVO_MOVE_SECONDS)
            self.pwm.ChangeDutyCycle(0)

        self.is_open = should_open

    def stop(self):
        self.pwm.ChangeDutyCycle(0)
        self.pwm.stop()


class Display:
    def __init__(self):
        self.lcd = CharLCD(
            i2c_expander="PCF8574",
            address=LCD_ADDRESS,
            port=1,
            cols=16,
            rows=2,
            charmap="A00",
            expander_params={
                "rs": 0,
                "rw": 1,
                "e": 2,
                "data": [4, 5, 6, 7],
                "backlight": 3,
            },
        )
        self.last_lines = None
        self.last_backlight = None
        self.lcd.clear()

    def show(self, line1, line2, backlight=True):
        lines = (line1[:16].ljust(16), line2[:16].ljust(16))
        if lines != self.last_lines:
            for row, text in enumerate(lines):
                self.lcd.cursor_pos = (row, 0)
                self.lcd.write_string(text)
            self.last_lines = lines
        if backlight != self.last_backlight:
            self.lcd.backlight_enabled = backlight
            self.last_backlight = backlight

    def close(self):
        self.lcd.close(clear=True)


def update_latched(value, threshold, hysteresis, previous):
    """Bat o nguong, tat thap hon nguong mot khoang de tranh relay rung."""
    if previous:
        return value >= threshold - hysteresis
    return value >= threshold


class LaptopBridge:
    """Gui lua cam bien sang laptop va nhan trang thai AI ve Pi."""

    def __init__(self, laptop, port, token):
        self.url = "http://%s:%d/pi-fire" % (laptop, port)
        self.token = token
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.sensor_fire = False
        self.remote_ai_fire = False
        self.last_valid_response = 0.0
        # None de lan thu ket noi dau tien luon in thanh cong hoac that bai.
        self.online = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def set_sensor_fire(self, active):
        with self.lock:
            self.sensor_fire = bool(active)

    def ai_fire(self):
        with self.lock:
            fresh = (
                time.monotonic() - self.last_valid_response
                <= AI_STATUS_TIMEOUT_SECONDS
            )
            return self.remote_ai_fire and fresh

    def _set_online(self, online, message=None):
        if online != self.online:
            self.online = online
            if online:
                print("[LAPTOP AI] Da ket noi", flush=True)
            else:
                print(
                    "[LAPTOP AI] Mat ket noi%s"
                    % ((": " + message) if message else ""),
                    flush=True,
                )

    def _run(self):
        while not self.stop_event.is_set():
            with self.lock:
                sensor_fire = self.sensor_fire

            body = json.dumps(
                {"version": 1, "fire": sensor_fire}
            ).encode("utf-8")
            request = Request(
                self.url,
                data=body,
                method="POST",
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Content-Type": "application/json",
                },
            )

            try:
                with urlopen(request, timeout=0.6) as response:
                    raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Phan hoi AI qua lon")
                payload = json.loads(raw.decode("utf-8"))
                cameras = payload.get("cameras")
                if payload.get("version") != 1 or not isinstance(cameras, list):
                    raise ValueError("Phan hoi AI khong hop le")
                ai_fire = any(
                    isinstance(item, dict) and item.get("state") == "fire"
                    for item in cameras
                )
                with self.lock:
                    self.remote_ai_fire = ai_fire
                    self.last_valid_response = time.monotonic()
                self._set_online(True)
            except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._set_online(False, str(exc))

            self.stop_event.wait(NETWORK_INTERVAL_SECONDS)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laptop", default="192.168.1.49")
    parser.add_argument("--ai-port", type=int, default=8080)
    args = parser.parse_args()

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(FAN_PIN, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(WARNING_LED_PIN, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(FLAME_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(LIGHT_PIN, GPIO.IN)

    door = None
    display = None
    rfid = None
    i2c = None
    bridge = None

    try:
        door = Door(SERVO_PIN)
        display = Display()

        i2c = busio.I2C(board.SCL, board.SDA)
        environment = adafruit_ahtx0.AHTx0(i2c)
        ads = ADS.ADS1115(i2c, address=ADS1115_ADDRESS)
        gas_channel = AnalogIn(ads, GAS_ADC_PIN)

        try:
            rfid = MFRC522I2C(address=RFID_ADDRESS)
            print("[RFID] San sang tai 0x%02X" % RFID_ADDRESS)
        except RuntimeError as exc:
            # Cam bien khac van tiep tuc chay neu RFID dang mat ket noi.
            print("[RFID] %s. Tam bo qua RFID." % exc, flush=True)

        door.set_open(False, force=True)
        display.show("CANH MINH", "SMARTHOME AI")

        token = os.environ.get("CAMERA_TOKEN", "")
        if token:
            bridge = LaptopBridge(args.laptop, args.ai_port, token)
            bridge.start()
        else:
            print(
                "[LAPTOP AI] CAMERA_TOKEN chua duoc dat; ket noi AI bi tat.",
                flush=True,
            )
        print("He thong Smarthome da san sang. Ctrl+C de dung.", flush=True)

        temperature = None
        humidity = None
        gas_voltage = 0.0
        gas_warning = False
        gas_danger = False
        rfid_open_until = 0.0
        last_uid = None
        last_uid_time = 0.0
        last_env_sample = 0.0
        last_gas_sample = 0.0
        last_rfid_sample = 0.0
        last_env_display = None
        env_display_until = 0.0
        led_on = False
        last_led_toggle = 0.0
        last_status = None
        light_candidate = None
        light_stable_count = 0
        light_state = None
        light_display_until = 0.0
        last_sensor_fire = float("-inf")

        while True:
            now = time.monotonic()

            raw_sensor_fire = GPIO.input(FLAME_PIN) == GPIO.LOW
            if raw_sensor_fire:
                last_sensor_fire = now
            sensor_fire = raw_sensor_fire or (
                now - last_sensor_fire <= FLAME_HOLD_SECONDS
            )
            if bridge is not None:
                bridge.set_sensor_fire(sensor_fire)
                ai_fire = bridge.ai_fire()
            else:
                ai_fire = False
            fire = sensor_fire or ai_fire

            # Chi chap nhan trang thai anh sang sau 3 lan doc giong nhau.
            # LCD chi duoc ghi lai khi light_state thuc su thay doi.
            current_light = GPIO.input(LIGHT_PIN)
            if current_light == light_candidate:
                light_stable_count += 1
            else:
                light_candidate = current_light
                light_stable_count = 1

            if (
                light_stable_count >= LIGHT_STABLE_READS
                and light_candidate != light_state
            ):
                light_state = light_candidate
                light_display_until = now + LIGHT_DISPLAY_SECONDS
                print(
                    "[ANH SANG] %s"
                    % ("TROI SANG" if light_state else "TROI TOI"),
                    flush=True,
                )

            if now - last_gas_sample >= 0.20:
                try:
                    gas_voltage = gas_channel.voltage
                    gas_warning = update_latched(
                        gas_voltage,
                        GAS_WARNING_V,
                        GAS_HYSTERESIS_V,
                        gas_warning,
                    )
                    gas_danger = update_latched(
                        gas_voltage,
                        GAS_DANGER_V,
                        GAS_HYSTERESIS_V,
                        gas_danger,
                    )
                except (OSError, ValueError) as exc:
                    print("[GAS] Loi doc: %s" % exc, flush=True)
                last_gas_sample = now

            if now - last_env_sample >= 2.0:
                try:
                    new_temperature = float(environment.temperature)
                    new_humidity = float(environment.relative_humidity)
                    if last_env_display is None:
                        last_env_display = (new_temperature, new_humidity)
                    elif (
                        abs(new_temperature - last_env_display[0]) >= 0.5
                        or abs(new_humidity - last_env_display[1]) >= 1.0
                    ):
                        env_display_until = now + ENV_DISPLAY_SECONDS
                        last_env_display = (new_temperature, new_humidity)
                    temperature = new_temperature
                    humidity = new_humidity
                    print(
                        "[MOI TRUONG] %.1f C | %.1f %% | Gas %.2f V"
                        % (temperature, humidity, gas_voltage),
                        flush=True,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    print("[AHT] Loi doc: %s" % exc, flush=True)
                last_env_sample = now

            if rfid is not None and now - last_rfid_sample >= 0.15:
                uid = rfid.read_uid()
                if uid and (uid != last_uid or now - last_uid_time >= 2.0):
                    print("[RFID] NHAN THE: %s" % uid, flush=True)
                    rfid_open_until = now + RFID_OPEN_SECONDS
                    last_uid = uid
                    last_uid_time = now
                last_rfid_sample = now

            temp_high = temperature is not None and temperature > TEMP_THRESHOLD_C
            humidity_high = humidity is not None and humidity >= HUMIDITY_THRESHOLD
            rfid_open = now < rfid_open_until

            # Mot noi duy nhat quyet dinh cua va quat, tranh cac cam bien tranh chap.
            door_should_open = fire or gas_warning or rfid_open
            fan_should_run = fire or gas_danger or temp_high or humidity_high
            door.set_open(door_should_open)
            GPIO.output(FAN_PIN, GPIO.HIGH if fan_should_run else GPIO.LOW)

            if fire:
                if now - last_led_toggle >= LED_BLINK_SECONDS:
                    led_on = not led_on
                    GPIO.output(
                        WARNING_LED_PIN,
                        GPIO.HIGH if led_on else GPIO.LOW,
                    )
                    last_led_toggle = now
            elif led_on:
                led_on = False
                GPIO.output(WARNING_LED_PIN, GPIO.LOW)

            # Uu tien LCD: lua > gas > nhiet/do am > RFID > moi truong
            # > anh sang. Display.show tu bo qua neu noi dung khong thay doi.
            if fire:
                if sensor_fire and ai_fire:
                    status = "FIRE_BOTH"
                elif ai_fire:
                    status = "FIRE_AI"
                else:
                    status = "FIRE_SENSOR"
                visible = int(now / LCD_BLINK_SECONDS) % 2 == 0
                display.show(
                    "CO LUA NGUY HIEM",
                    "RA KHOI NHA NGAY",
                    backlight=visible,
                )
            elif gas_danger:
                status = "GAS_DANGER"
                visible = int(now / LCD_BLINK_SECONDS) % 2 == 0
                display.show(
                    "GAS NGUY HIEM",
                    "MO CUA BAT QUAT",
                    backlight=visible,
                )
            elif gas_warning:
                status = "GAS_WARNING"
                display.show("CANH BAO CO GAS", "CUA DANG MO")
            elif temp_high or humidity_high:
                status = "ENV_HIGH"
                display.show(
                    "NHIET/DO AM CAO",
                    "T:%.1fC H:%.0f%%" % (temperature, humidity),
                )
            elif rfid_open:
                status = "RFID"
                display.show("THE RFID HOP LE", "CUA DANG MO")
            elif now < env_display_until and temperature is not None:
                status = "ENV_CHANGED"
                display.show(
                    "T: %.1f C" % temperature,
                    "DO AM: %.1f %%" % humidity,
                )
            elif light_state is not None and now < light_display_until:
                status = "LIGHT_%d" % light_state
                display.show(
                    "SMARTHOME AI",
                    "TROI SANG" if light_state else "TROI TOI",
                )
            else:
                status = "NORMAL"
                display.show("CANH MINH", "SMARTHOME AI")

            if status != last_status:
                print(
                    "[TRANG THAI] %s | Quat=%s | Cua=%s"
                    % (
                        status,
                        "BAT" if fan_should_run else "TAT",
                        "MO" if door_should_open else "DONG",
                    ),
                    flush=True,
                )
                last_status = status

            time.sleep(0.03)

    except KeyboardInterrupt:
        print("\nDang dung he thong...", flush=True)
    finally:
        if bridge is not None:
            bridge.stop()
        GPIO.output(FAN_PIN, GPIO.LOW)
        GPIO.output(WARNING_LED_PIN, GPIO.LOW)
        if door is not None:
            try:
                door.set_open(False, force=True)
            finally:
                door.stop()
        if rfid is not None:
            rfid.close()
        if display is not None:
            display.close()
        if i2c is not None:
            i2c.deinit()
        GPIO.cleanup()
        print("Da tat quat, LED, dong cua va don dep GPIO.", flush=True)


if __name__ == "__main__":
    main()

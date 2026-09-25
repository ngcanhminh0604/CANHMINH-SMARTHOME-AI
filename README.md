# CANH MINH SMARTHOME AI

A Raspberry Pi 4 smart-home system combined with a laptop-based AI model for
fire, gas, and environmental monitoring. The Raspberry Pi controls the door
servo, fan, warning LED, and LCD. The laptop processes two cameras concurrently
with `FireVisionAI.pt` and plays a continuous fire alarm.

> This is an educational prototype, not a certified life-safety system. Do not
> use it as a replacement for certified smoke detectors or fire alarms.

## Features

- Monitors a digital flame sensor on GPIO16.
- Runs fire detection on the laptop camera and a USB webcam concurrently.
- Exchanges fire status between the laptop and Raspberry Pi over the LAN.
- Plays a continuous alarm on the laptop while either source reports fire.
- Opens the door, starts the fan, and flashes the warning LED during a fire.
- Supports warning and danger levels for the gas sensor.
- Monitors temperature and humidity and starts the fan above configured limits.
- Opens the door temporarily after an RFID card is detected.
- Reports changes between bright and dark conditions on the LCD.
- Returns the LCD to `CANH MINH / SMARTHOME AI` after normal notifications.
- Holds fire alerts for three seconds to prevent flicker between AI frames.

## System Architecture

```text
Camera 0 + Camera 1
          |
          v
Laptop runs FireVisionAI.pt ---- continuous fire alarm audio
          |
          | HTTP over LAN, port 8080
          v
Raspberry Pi 4 <---- flame, gas, AHTx0, RFID, and light sensors
          |
          +---- door servo
          +---- fan relay
          +---- warning LED
          +---- 16x2 LCD
```

The laptop and Pi use the same `CAMERA_TOKEN`. The Pi sends its physical flame
sensor state to the laptop, while the laptop returns the current state of both
cameras approximately every 0.15 seconds. If the network connection is lost,
the Raspberry Pi sensors and actuators continue operating locally.

## Hardware

- Raspberry Pi 4 with 4 GB RAM and a 256 GB microSD card.
- Windows laptop with an integrated camera.
- USB webcam.
- Door servo.
- 16x2 I²C LCD with a PCF8574 expander.
- Digital flame sensor.
- Analog gas sensor connected through an ADS1115.
- AHTx0 temperature and humidity sensor.
- I²C RFID reader.
- Digital light sensor.
- Fan, relay module, and warning LED.

## Raspberry Pi Wiring

The program uses **BCM GPIO numbering**.

| Device | GPIO/address | Purpose |
|---|---:|---|
| Door servo | GPIO19 | 50 Hz PWM signal |
| Fan relay | GPIO20 | HIGH is on, LOW is off |
| Flame sensor | GPIO16 | LOW means fire detected |
| Warning LED | GPIO5 | Flashes during a fire alert |
| Light sensor | GPIO8 | LOW is dark, HIGH is bright |
| PCF8574 LCD | I²C `0x21` | 16x2 status display |
| ADS1115 | I²C `0x49` | Gas sensor on channel A0 |
| RFID reader | I²C `0x2C` | Reads card UIDs |
| AHTx0 | Default I²C address | Temperature and humidity |
| SDA | GPIO2, physical pin 3 | I²C data |
| SCL | GPIO3, physical pin 5 | I²C clock |

Power the servo from a separate 5 V supply with sufficient current, and connect
the supply ground to the Raspberry Pi ground. An undersized supply or missing
common ground can cause servo jitter, Pi resets, and I²C communication errors.

## Default Configuration

| Setting | Default |
|---|---:|
| Door closed angle | `0°` |
| Door open angle | `175°` |
| RFID door-open duration | `5 seconds` |
| Gas warning threshold | `2.0 V` |
| Gas danger threshold | `2.5 V` |
| Gas hysteresis | `0.10 V` |
| Temperature threshold | `30°C` |
| Humidity threshold | `80%` |
| Physical flame alert hold | `3 seconds` |
| AI server port | `8080` |

Calibrate the gas thresholds for the actual sensor after it has warmed up. Do
not apply a voltage to the ADS1115 that exceeds the ADC hardware limits.

## Project Structure

```text
camerafire/
├── main.py                    # Runs on the Raspberry Pi
├── laptop_fire_ai.py          # Runs AI and alarm audio on the laptop
├── FireVisionAI.pt            # Fire/smoke detection model
├── fire_alarm.mp3             # Continuously looping alarm audio
├── requirements-pi.txt        # Raspberry Pi dependencies
├── requirements-laptop.txt    # Laptop dependencies
└── README.md
```

Do not commit `.venv`, `__pycache__`, `.env`, or a real shared token to GitHub.

## Laptop Installation

Open PowerShell:

```powershell
cd D:\2026\camerafire
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-laptop.txt
```

Check that the model loads and inspect its class names:

```powershell
python laptop_fire_ai.py --model FireVisionAI.pt --list-classes
```

The current model contains the `fire` and `smoke` classes.

## Raspberry Pi Installation

Enable I²C and install the system packages:

```bash
sudo raspi-config nonint do_i2c 0
sudo apt update
sudo apt install -y i2c-tools python3-venv python3-pip
sudo reboot
```

After the Pi restarts:

```bash
cd /home/pi/Test
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
python -m pip install -r requirements-pi.txt
```

Check the I²C devices:

```bash
sudo i2cdetect -y 1
```

The output should include addresses such as `21`, `2c`, `49`, and the AHTx0
address. If `/dev/i2c-1` does not exist, I²C has not been enabled or the Pi has
not been restarted since changing the setting.

## Copying the Pi Program

Run from PowerShell on the laptop:

```powershell
scp "D:\2026\camerafire\main.py" pi@192.168.1.59:/home/pi/Test/main.py
scp "D:\2026\camerafire\requirements-pi.txt" pi@192.168.1.59:/home/pi/Test/requirements-pi.txt
```

## Running the Complete System

### 1. Find the laptop IP address

```powershell
ipconfig
```

Find the Wi-Fi `IPv4 Address`. The current example is `192.168.1.49`. This
address can change after reconnecting to Wi-Fi. Configure a DHCP reservation in
the router if the laptop should always use the same address.

### 2. Start the AI application on the laptop

```powershell
cd D:\2026\camerafire
$env:CAMERA_TOKEN="YOUR_SHARED_TOKEN"

.\.venv\Scripts\python.exe .\laptop_fire_ai.py `
  --model .\FireVisionAI.pt `
  --cameras 0 1 `
  --device cpu `
  --imgsz 320 `
  --conf 0.30 `
  --fire-hold 3.0 `
  --alarm-file .\fire_alarm.mp3 `
  --alarm-volume 1.0
```

Keep the PowerShell window open. Press `Q` in a camera window or `Ctrl+C` to
stop. If the laptop has an NVIDIA GPU and PyTorch detects CUDA, replace
`--device cpu` with `--device 0`.

### 3. Start the Raspberry Pi application

The token must exactly match the token used on the laptop:

```bash
cd /home/pi/Test
source .venv/bin/activate
export CAMERA_TOKEN='YOUR_SHARED_TOKEN'

python main.py \
  --laptop 192.168.1.49 \
  --ai-port 8080
```

After a successful connection, the Pi prints:

```text
[LAPTOP AI] Da ket noi
```

## Testing the Network Connection

Run from the Pi and replace the token and IP address as needed:

```bash
curl -H "Authorization: Bearer YOUR_SHARED_TOKEN" \
  http://192.168.1.49:8080/status
```

A normal response looks like this:

```json
{
  "version": 1,
  "cameras": [
    {"camera": 0, "state": "clear"},
    {"camera": 1, "state": "clear"}
  ]
}
```

When the AI detects fire, the corresponding camera returns `"state": "fire"`.

If Windows Firewall blocks the connection, create an inbound TCP rule for port
`8080`. On a Public network, restrict the rule's remote IP to the Raspberry Pi,
for example `192.168.1.59`.

## State Priority

The LCD and actuator priority is:

1. Fire reported by the physical sensor or camera AI.
2. Dangerous gas level.
3. Gas warning level.
4. High temperature or humidity.
5. RFID card detected.
6. Temperature or humidity change.
7. Light level change.
8. Normal state.

During normal operation, the LCD displays:

```text
CANH MINH
SMARTHOME AI
```

## Fire Alert Behavior

When either fire source becomes active:

- The door opens immediately to `175°`.
- The fan starts.
- The LED on GPIO5 flashes rapidly.
- The LCD shows an evacuation warning.
- The laptop plays `fire_alarm.mp3` continuously.

The alarm stops after both the AI and physical sensor no longer report fire and
the three-second hold period has expired. Gas or environmental alerts can still
keep the fan or door active according to their own rules.

## AI Tuning

Reduce missed detections:

```powershell
--conf 0.25
```

Reduce false detections:

```powershell
--conf 0.35
```

Keep an unstable fire detection active for longer:

```powershell
--fire-hold 5.0
```

Treat both smoke and fire as an emergency:

```powershell
--fire-classes fire smoke
```

Set the alarm volume from `0.0` to `1.0`:

```powershell
--alarm-volume 0.7
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'cv2'`

The wrong Python interpreter is active, or the dependencies are missing:

```powershell
cd D:\2026\camerafire
.\.venv\Scripts\python.exe -m pip install -r requirements-laptop.txt
```

### The Pi does not print `[LAPTOP AI] Da ket noi`

- Confirm that the laptop AI program is running.
- Check the current laptop IP with `ipconfig`.
- Confirm that both machines use the same token.
- Check TCP port 8080 in Windows Firewall.
- Run the `curl` command from the network test section.

### A camera reports `unknown`

- Close other applications using the camera.
- Try `--cameras 0 2` instead of `--cameras 0 1`.
- Check the USB webcam in Windows Camera or Device Manager.

### Fire detection is intermittent

- Use `--conf 0.25` or `--conf 0.30`.
- Increase `--fire-hold` to five seconds.
- Improve scene lighting and reduce the distance to the monitored area.
- Check that the training data is representative of the real camera scene.

### The servo jitters or moves to the wrong angle

- Check the servo power supply and common ground.
- Do not run multiple programs that control GPIO19.
- Confirm `CLOSE_ANGLE = 0.0` and `OPEN_ANGLE = 175.0`.
- Stop the program if the mechanism reaches a physical limit.

### The LCD flickers

`main.py` only writes when the displayed content changes. Do not run old LCD
test programs at the same time because they may repeatedly call `lcd.clear()`
and compete for the I²C bus.

### The RFID reader does not return a UID

- Check address `0x2C` with `i2cdetect`.
- Check SDA, SCL, power, and ground wiring.
- If RFID initialization fails, the rest of the system continues running.

## Alarm Audio Attribution

`fire_alarm.mp3` is a transcoded version of **NFPA Fire Alarm** by Awesome
Aasim. The file is identified as public domain on Wikimedia Commons:

<https://commons.wikimedia.org/wiki/File:NFPA_Fire_Alarm.ogg>

The laptop program uses Windows MCI (`winmm`) to loop the MP3 continuously, so
it does not require `pygame` or an external media player.

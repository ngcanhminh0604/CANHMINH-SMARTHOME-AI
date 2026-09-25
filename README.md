# CANH MINH SMARTHOME AI

Project gom cam bien lua, gas, AHTx0, RFID, LCD, servo, quat va LED canh bao
vao mot chuong trinh duy nhat tren Raspberry Pi 4.

Project cung co `laptop_fire_ai.py` de chay FireVisionAI tren hai camera laptop.
Laptop va Pi trao doi trang thai hai chieu qua mang LAN.

## Ket noi dang dung

- Servo PWM: GPIO19; dong `0 do`, mo `175 do`.
- Relay quat: GPIO20, muc HIGH la bat.
- Cam bien lua: GPIO16, muc LOW la co lua.
- Cam bien anh sang: GPIO8; LOW la troi toi, HIGH la troi sang.
- LED canh bao don: GPIO5.
- LCD PCF8574: I2C `0x21`, 16x2.
- ADS1115: I2C `0x49`, cam bien gas o kenh A0.
- RFID: I2C `0x2C`.
- AHTx0: I2C mac dinh cua cam bien.

## Cai dat tren Raspberry Pi

```bash
cd /home/pi/Test
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements-pi.txt
python3 main.py
```

Chi chay `main.py`; khong chay dong thoi cac file cam bien cu vi chung se tranh
chap GPIO19, GPIO20 va LCD.

Code tu dong tuong thich voi ca hai kieu khai bao kenh ADS1115: `Pin.A0` cua
thu vien moi va `ADS.P0` cua thu vien cu.

## Nguong dang cau hinh

- Gas canh bao tu `2.0 V`: LCD canh bao va mo cua.
- Gas nguy hiem tu `2.5 V`: bat them quat.
- Nhiet do tren `30 C`: bat quat.
- Do am tu `80%`: bat quat; khi xuong duoi `80%` thi tat neu khong con canh bao khac.

Sua cac hang `GAS_WARNING_V`, `GAS_DANGER_V`, `TEMP_THRESHOLD_C` va
`HUMIDITY_THRESHOLD` o dau file `main.py` neu can hieu chinh lai.

LCD uu tien hien thi lua, gas, nhiet/do am cao va RFID. Khi anh sang chuyen
trang thai, LCD hien thi trong 3 giay:

```text
SMARTHOME AI
TROI SANG
```

hoac:

```text
SMARTHOME AI
TROI TOI
```

Sau do LCD tu tro ve trang thai binh thuong:

```text
CANH MINH
SMARTHOME AI
```

Neu anh sang khong thay doi, LCD khong ghi lai thong bao nen khong nhap nhay.

## Ket noi Laptop AI va Raspberry Pi

Dia chi dang dung:

- Laptop: `192.168.1.49`.
- Raspberry Pi: `192.168.1.59`.
- Cong AI: `8080`.

Hai may phai dat cung mot `CAMERA_TOKEN`. Khi cam bien lua GPIO16 cua Pi bat,
Pi gui trang thai sang laptop de laptop keu bip. Khi mot trong hai camera AI
phat hien lua, laptop gui trang thai ve Pi de mo cua, bat quat va nhap nhay LED.

### Chuan bi tren laptop Windows

Mo PowerShell tai thu muc laptop:

```powershell
cd D:\2026\camerafire
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-laptop.txt
```

Model laptop dat tai:

```powershell
D:\2026\camerafire\FireVisionAI.pt
```

Chay AI voi camera laptop `0` va webcam ngoai `1`:

```powershell
$env:CAMERA_TOKEN="canhminh-smarthome-2026"
python laptop_fire_ai.py --model FireVisionAI.pt --cameras 0 1 --device cpu --imgsz 320 --conf 0.4
```

Am bao mac dinh doc file `fire_alarm.mp3` va phat lap lien tuc den khi ca AI va
cam bien lua tren Pi deu bao het lua. Chinh am luong bang `--alarm-volume`:

```powershell
python laptop_fire_ai.py --model FireVisionAI.pt --cameras 0 1 --device cpu --alarm-file fire_alarm.mp3 --alarm-volume 1.0
```

AI va cam bien GPIO16 giu trang thai bao lua them 3 giay ke tu lan cuoi nhin
thay lua. Vi vay mat nhan dien trong vai frame se khong lam tat/mo canh bao lien
tuc. Co the doi thoi gian AI bang `--fire-hold 3.0`. Neu AI bo sot lua nhieu,
ha `--conf` tu `0.4` xuong `0.25`.

File am thanh: `NFPA Fire Alarm.ogg`, tac gia Awesome Aasim, public domain,
nguon Wikimedia Commons.

Neu laptop co GPU NVIDIA va PyTorch nhan duoc CUDA, thay `--device cpu` bang
`--device 0`. Neu Windows hien hop thoai Firewall, cho phep Python tren mang
Private de Pi ket noi duoc cong 8080.

### Chuan bi va chay tren Pi

Tu laptop, chep file Pi moi:

```powershell
scp "D:\2026\camerafire\main.py" pi@192.168.1.59:/home/pi/Test/main.py
```

Tren Pi:

```bash
cd /home/pi/Test
source .venv/bin/activate
export CAMERA_TOKEN='canhminh-smarthome-2026'
python main.py --laptop 192.168.1.49 --ai-port 8080
```

Nen chay laptop AI truoc, sau do chay `main.py` tren Pi. Khi ket noi thanh
cong, terminal Pi se in `[LAPTOP AI] Da ket noi`.

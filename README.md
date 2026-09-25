# CANH MINH SMARTHOME AI

Hệ thống nhà thông minh dùng Raspberry Pi 4 kết hợp mô hình AI trên laptop để
phát hiện lửa, khí gas và các trạng thái môi trường. Raspberry Pi điều khiển
cửa servo, quạt, LED cảnh báo và LCD. Laptop xử lý đồng thời hai camera bằng
model `FireVisionAI.pt` và phát âm thanh báo cháy liên tục.

> Đây là mô hình thử nghiệm và học tập, không phải thiết bị báo cháy đã được
> chứng nhận. Không dùng hệ thống này để thay thế thiết bị báo cháy chuyên dụng.

## Chức năng

- Theo dõi cảm biến lửa GPIO16.
- Chạy AI nhận diện lửa đồng thời trên camera laptop và webcam USB.
- Trao đổi trạng thái hai chiều giữa laptop và Raspberry Pi qua mạng LAN.
- Phát âm thanh liên tục trên laptop khi AI hoặc cảm biến phát hiện lửa.
- Tự động mở cửa, bật quạt và nhấp nháy LED khi có lửa.
- Cảnh báo gas theo hai mức và tự động mở cửa/bật quạt.
- Theo dõi nhiệt độ, độ ẩm và bật quạt khi vượt ngưỡng.
- Đọc thẻ RFID để mở cửa trong thời gian đặt trước.
- Hiển thị trạng thái ánh sáng khi chuyển giữa trời sáng và trời tối.
- Tự động trở về `CANH MINH / SMARTHOME AI` sau thông báo thường.
- Giữ cảnh báo lửa thêm 3 giây để tránh chập chờn giữa các frame.

## Luồng hoạt động

```text
Camera 0 + Camera 1
          |
          v
Laptop chạy FireVisionAI.pt ---- phát âm thanh báo cháy
          |
          | HTTP LAN, cổng 8080
          v
Raspberry Pi 4 <---- cảm biến lửa, gas, AHTx0, RFID, ánh sáng
          |
          +---- servo cửa
          +---- relay quạt
          +---- LED cảnh báo
          +---- LCD 16x2
```

Laptop và Pi dùng cùng một `CAMERA_TOKEN`. Pi gửi trạng thái cảm biến lửa sang
laptop; laptop trả trạng thái của hai camera về Pi khoảng mỗi 0,15 giây. Nếu
mất kết nối, cảm biến và cơ cấu trên Pi vẫn tiếp tục hoạt động độc lập.

## Phần cứng

- Raspberry Pi 4, RAM 4 GB và thẻ nhớ 256 GB.
- Laptop Windows, camera tích hợp và webcam USB.
- Servo điều khiển cửa.
- LCD I²C 16x2 dùng PCF8574.
- Cảm biến lửa digital.
- Cảm biến gas analog qua ADS1115.
- Cảm biến nhiệt độ/độ ẩm AHTx0.
- Đầu đọc RFID I²C.
- Cảm biến ánh sáng digital.
- Relay, quạt và LED cảnh báo đơn.

## Kết nối Raspberry Pi

Chương trình sử dụng cách đánh số chân **BCM**.

| Thiết bị | GPIO/địa chỉ | Chức năng |
|---|---:|---|
| Servo cửa | GPIO19 | Tín hiệu PWM 50 Hz |
| Relay quạt | GPIO20 | HIGH bật, LOW tắt |
| Cảm biến lửa | GPIO16 | LOW là phát hiện lửa |
| LED cảnh báo | GPIO5 | Nhấp nháy khi có lửa |
| Cảm biến ánh sáng | GPIO8 | LOW tối, HIGH sáng |
| LCD PCF8574 | I²C `0x21` | LCD 16x2 |
| ADS1115 | I²C `0x49` | Cảm biến gas ở kênh A0 |
| RFID | I²C `0x2C` | Đọc UID thẻ |
| AHTx0 | I²C mặc định | Nhiệt độ và độ ẩm |
| SDA | GPIO2, chân vật lý 3 | Dữ liệu I²C |
| SCL | GPIO3, chân vật lý 5 | Clock I²C |

Servo nên dùng nguồn 5 V riêng đủ dòng và nối chung GND với Raspberry Pi. Nguồn
yếu hoặc không chung GND có thể làm servo rung, Pi khởi động lại hoặc I²C lỗi.

## Cấu hình mặc định

| Cấu hình | Giá trị |
|---|---:|
| Góc đóng cửa | `0°` |
| Góc mở cửa | `175°` |
| Thời gian mở bằng RFID | `5 giây` |
| Gas cảnh báo | `2.0 V` |
| Gas nguy hiểm | `2.5 V` |
| Độ trễ gas | `0.10 V` |
| Ngưỡng nhiệt độ | `30°C` |
| Ngưỡng độ ẩm | `80%` |
| Giữ cảnh báo cảm biến lửa | `3 giây` |
| Cổng kết nối AI | `8080` |

Hai ngưỡng gas cần được hiệu chỉnh theo cảm biến thực tế sau thời gian làm nóng.
Không cấp vào ADS1115 điện áp vượt quá giới hạn phần cứng của ADC.

## Cấu trúc project

```text
camerafire/
├── main.py                    # Chạy trên Raspberry Pi
├── laptop_fire_ai.py          # Chạy AI và âm thanh trên laptop
├── FireVisionAI.pt            # Model nhận diện fire/smoke
├── fire_alarm.mp3             # Âm thanh báo cháy lặp liên tục
├── requirements-pi.txt        # Thư viện Raspberry Pi
├── requirements-laptop.txt    # Thư viện laptop
└── README.md
```

Không đưa `.venv`, `__pycache__`, file `.env` hoặc token thật lên GitHub.

## Cài đặt trên laptop Windows

```powershell
cd D:\2026\camerafire
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-laptop.txt
```

Kiểm tra model và tên lớp:

```powershell
python laptop_fire_ai.py --model FireVisionAI.pt --list-classes
```

Model hiện tại có hai lớp `fire` và `smoke`.

## Cài đặt trên Raspberry Pi

Bật I²C:

```bash
sudo raspi-config nonint do_i2c 0
sudo apt update
sudo apt install -y i2c-tools python3-venv python3-pip
sudo reboot
```

Sau khi Pi khởi động lại:

```bash
cd /home/pi/Test
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
python -m pip install -r requirements-pi.txt
```

Kiểm tra thiết bị I²C:

```bash
sudo i2cdetect -y 1
```

Kết quả cần thấy các địa chỉ đang sử dụng như `21`, `2c`, `49` và địa chỉ của
AHTx0. Nếu `/dev/i2c-1` không tồn tại, I²C chưa được bật hoặc Pi chưa khởi động
lại sau khi thay đổi cấu hình.

## Chép chương trình Pi

Từ PowerShell trên laptop:

```powershell
scp "D:\2026\camerafire\main.py" pi@192.168.1.59:/home/pi/Test/main.py
scp "D:\2026\camerafire\requirements-pi.txt" pi@192.168.1.59:/home/pi/Test/requirements-pi.txt
```

## Chạy toàn bộ hệ thống

### 1. Xác định IP laptop

```powershell
ipconfig
```

Tìm `IPv4 Address` của Wi-Fi. Ví dụ hiện tại là `192.168.1.49`. IP có thể thay
đổi khi kết nối lại Wi-Fi; nên đặt DHCP reservation nếu muốn giữ cố định.

### 2. Chạy AI trên laptop

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

Giữ cửa sổ này mở. Nhấn `Q` tại cửa sổ camera hoặc `Ctrl+C` để dừng. Nếu laptop
có GPU NVIDIA và PyTorch nhận CUDA, có thể thay `--device cpu` bằng `--device 0`.

### 3. Chạy trên Raspberry Pi

Token phải giống hệt token trên laptop:

```bash
cd /home/pi/Test
source .venv/bin/activate
export CAMERA_TOKEN='YOUR_SHARED_TOKEN'

python main.py \
  --laptop 192.168.1.49 \
  --ai-port 8080
```

Khi kết nối thành công, Pi in:

```text
[LAPTOP AI] Da ket noi
```

## Kiểm tra kết nối mạng

Từ Pi, thay token và IP cho đúng:

```bash
curl -H "Authorization: Bearer YOUR_SHARED_TOKEN" \
  http://192.168.1.49:8080/status
```

Phản hồi bình thường:

```json
{
  "version": 1,
  "cameras": [
    {"camera": 0, "state": "clear"},
    {"camera": 1, "state": "clear"}
  ]
}
```

Khi AI phát hiện lửa, camera tương ứng trả về `"state": "fire"`. Nếu Windows
Firewall chặn kết nối, tạo Inbound Rule TCP cổng `8080`. Trên mạng Public nên
giới hạn Remote IP là địa chỉ Pi, ví dụ `192.168.1.59`.

## Thứ tự ưu tiên

1. Lửa từ cảm biến hoặc camera AI.
2. Gas nguy hiểm.
3. Gas cảnh báo.
4. Nhiệt độ hoặc độ ẩm cao.
5. Thẻ RFID hợp lệ.
6. Thay đổi nhiệt độ/độ ẩm.
7. Thay đổi sáng/tối.
8. Trạng thái bình thường.

Ở trạng thái bình thường LCD hiển thị:

```text
CANH MINH
SMARTHOME AI
```

## Hành vi cảnh báo lửa

Khi một trong hai nguồn báo lửa:

- Cửa mở ngay đến `175°`.
- Quạt bật.
- LED GPIO5 nhấp nháy nhanh.
- LCD hiển thị cảnh báo rời khỏi nhà.
- Laptop phát `fire_alarm.mp3` và lặp liên tục.

Âm thanh và trạng thái lửa dừng khi cả AI và cảm biến đều không còn báo lửa,
sau thời gian giữ cảnh báo 3 giây. Cảnh báo gas hoặc môi trường vẫn có thể tiếp
tục giữ quạt/cửa theo logic riêng.

## Điều chỉnh AI

Giảm bỏ sót lửa:

```powershell
--conf 0.25
```

Giảm cảnh báo nhầm:

```powershell
--conf 0.35
```

Giữ cảnh báo lâu hơn khi nhận diện chập chờn:

```powershell
--fire-hold 5.0
```

Nhận diện cả khói và lửa:

```powershell
--fire-classes fire smoke
```

Thay đổi âm lượng từ `0.0` đến `1.0`:

```powershell
--alarm-volume 0.7
```

## Xử lý lỗi thường gặp

### `ModuleNotFoundError: No module named 'cv2'`

```powershell
cd D:\2026\camerafire
.\.venv\Scripts\python.exe -m pip install -r requirements-laptop.txt
```

### Pi không hiện `[LAPTOP AI] Da ket noi`

- Kiểm tra AI laptop đang chạy.
- Kiểm tra IP laptop bằng `ipconfig`.
- Kiểm tra token hai máy giống nhau.
- Kiểm tra cổng TCP 8080 trong Windows Firewall.
- Chạy lệnh `curl` ở phần kiểm tra kết nối.

### Camera hiển thị `unknown`

- Đóng ứng dụng khác đang sử dụng camera.
- Thử đổi `--cameras 0 1` thành `--cameras 0 2`.
- Kiểm tra webcam USB trong Camera hoặc Device Manager của Windows.

### AI nhận lửa lúc có lúc không

- Chạy với `--conf 0.25` hoặc `--conf 0.30`.
- Tăng `--fire-hold` lên 5 giây.
- Tăng ánh sáng và giảm khoảng cách đến vùng cần quan sát.
- Kiểm tra dữ liệu huấn luyện có tương đồng với camera thực tế.

### Servo rung hoặc chạy sai góc

- Kiểm tra nguồn servo và dây GND chung.
- Không chạy nhiều chương trình cùng điều khiển GPIO19.
- Kiểm tra `CLOSE_ANGLE = 0.0` và `OPEN_ANGLE = 175.0`.
- Dừng chương trình nếu cơ cấu chạm giới hạn cơ khí.

### LCD nhấp nháy

`main.py` chỉ ghi LCD khi nội dung thay đổi. Không chạy đồng thời các file thử
LCD cũ vì chúng có thể gọi `lcd.clear()` liên tục và tranh chấp I²C.

### RFID không đọc được UID

- Kiểm tra địa chỉ `0x2C` bằng `i2cdetect`.
- Kiểm tra dây SDA, SCL, nguồn và GND.
- Nếu RFID không khởi tạo được, phần còn lại của hệ thống vẫn tiếp tục chạy.

## Âm thanh cảnh báo

`fire_alarm.mp3` là bản chuyển mã của **NFPA Fire Alarm**, tác giả Awesome
Aasim. Tệp được công bố thuộc phạm vi công cộng trên Wikimedia Commons:

<https://commons.wikimedia.org/wiki/File:NFPA_Fire_Alarm.ogg>

Chương trình dùng Windows MCI (`winmm`) để phát MP3 lặp liên tục, không cần cài
`pygame` hoặc trình phát âm thanh ngoài.

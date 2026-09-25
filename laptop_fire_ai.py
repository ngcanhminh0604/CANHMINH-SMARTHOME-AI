"""Run AI on laptop; expose detection status to Pi over a trusted LAN."""
import argparse
import ctypes
import hmac
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from ultralytics import YOLO

try:
    import winsound
except ImportError:
    winsound = None


class WindowsLoopingAudio:
    """Play an MP3 continuously with the Windows MCI audio service."""

    def __init__(self, path, volume=1.0):
        self.alias = 'smarthome_fire_alarm'
        self.winmm = ctypes.WinDLL('winmm')
        self.send = self.winmm.mciSendStringW
        self.send.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_void_p,
        ]
        self.send.restype = ctypes.c_uint
        self.opened = False
        resolved = str(Path(path).resolve())
        self._command(f'open "{resolved}" type mpegvideo alias {self.alias}')
        self.opened = True
        self._command(
            f'setaudio {self.alias} volume to {round(volume * 1000)}'
        )

    def _command(self, command):
        error_code = self.send(command, None, 0, None)
        if error_code:
            message = ctypes.create_unicode_buffer(256)
            self.winmm.mciGetErrorStringW(error_code, message, len(message))
            raise OSError(f'MCI error {error_code}: {message.value}')

    def play(self):
        self._command(f'seek {self.alias} to start')
        self._command(f'play {self.alias} repeat')

    def stop(self):
        if self.opened:
            self._command(f'stop {self.alias}')

    def close(self):
        if self.opened:
            self.send(f'close {self.alias}', None, 0, None)
            self.opened = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='FireVisionAI.pt')
    parser.add_argument('--cameras', nargs='+', type=int, default=[0])
    parser.add_argument('--device', default='cpu', help='cpu or CUDA device index such as 0')
    parser.add_argument('--imgsz', type=int, default=320)
    parser.add_argument('--conf', type=float, default=0.4)
    parser.add_argument('--fire-hold', type=float, default=3.0,
                        help='Keep FIRE active this many seconds after the last detection')
    parser.add_argument('--fire-classes', nargs='+', default=['fire'], help='Exact class names in model')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--list-classes', action='store_true')
    parser.add_argument('--mute-alarm', action='store_true',
                        help='Disable the laptop fire alarm sound')
    parser.add_argument('--alarm-file', type=Path, default=Path('fire_alarm.mp3'),
                        help='Audio file played continuously while fire is active')
    parser.add_argument('--alarm-volume', type=float, default=1.0,
                        help='Alarm volume from 0.0 to 1.0')
    parser.add_argument('--alarm-frequency', type=int, default=2600,
                        help='Alarm frequency in Hz (Windows: 37..32767)')
    parser.add_argument('--alarm-beep-ms', type=int, default=130,
                        help='Length of each alarm beep in milliseconds')
    parser.add_argument('--alarm-gap-ms', type=int, default=80,
                        help='Silence between quick beeps in milliseconds')
    parser.add_argument('--alarm-pause-ms', type=int, default=350,
                        help='Pause after each group of three beeps')
    args = parser.parse_args()
    if not 37 <= args.alarm_frequency <= 32767:
        parser.error('--alarm-frequency must be between 37 and 32767 Hz')
    if min(args.alarm_beep_ms, args.alarm_gap_ms, args.alarm_pause_ms) < 0:
        parser.error('Alarm timing values cannot be negative')
    if args.alarm_beep_ms == 0:
        parser.error('--alarm-beep-ms must be greater than zero')
    if not 0.0 <= args.alarm_volume <= 1.0:
        parser.error('--alarm-volume must be between 0.0 and 1.0')
    if args.fire_hold < 0:
        parser.error('--fire-hold cannot be negative')
    if not Path(args.model).is_file():
        parser.error(f'Model not found: {args.model}. Copy the model from Pi to laptop.')
    model = YOLO(args.model)
    print(f'Model classes: {model.names}', flush=True)
    if args.list_classes:
        return
    wanted = {name.casefold() for name in args.fire_classes}
    available = {str(name).casefold() for name in model.names.values()}
    if not wanted <= available:
        parser.error(f'Unknown fire class names: {wanted - available}. Use --fire-classes with actual names.')
    token = os.environ.get('CAMERA_TOKEN', '')
    if not token:
        parser.error('Set CAMERA_TOKEN on both laptop and Pi.')
    cameras = list(dict.fromkeys(args.cameras))
    frames, detections = {}, {}
    last_fire_seen = {}
    pi_sensor = {'fire': False, 'updated': 0.0}
    lock = threading.Lock()
    stop = threading.Event()

    def camera_records(now):
        records = []
        with lock:
            for index in cameras:
                item = frames.get(index)
                det = detections.get(index)
                valid = (not stop.is_set() and item is not None and det is not None
                         and now - item[0] < 2 and now - det['captured'] < 3)
                records.append({
                    'camera': index,
                    'state': ('fire' if det['fire'] else 'clear') if valid else 'unknown',
                })
        return records

    def capture(index):
        while not stop.is_set():
            cap = cv2.VideoCapture(index)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            try:
                if not cap.isOpened():
                    print(f'Camera {index} unavailable; retrying.', flush=True)
                while cap.isOpened() and not stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    with lock:
                        frames[index] = (time.monotonic(), frame)
                    stop.wait(0.01)
            finally:
                cap.release()
                with lock:
                    frames.pop(index, None)
                    detections.pop(index, None)
            stop.wait(2)

    def infer():
        processed = {}
        last_states = {}
        try:
            while not stop.is_set():
                batch = []
                now = time.monotonic()
                with lock:
                    snapshot = {index: frames.get(index) for index in cameras}

                for index in cameras:
                    item = snapshot[index]
                    if (item is not None
                            and item[0] != processed.get(index)
                            and now - item[0] <= 2):
                        batch.append((index, item[0], item[1]))

                if not batch:
                    stop.wait(0.002)
                    continue

                started = time.monotonic()
                results = model.predict(
                    [item[2] for item in batch],
                    imgsz=args.imgsz,
                    conf=args.conf,
                    device=args.device,
                    verbose=False,
                )
                inference_seconds = time.monotonic() - started

                for (index, captured, _), result in zip(batch, results):
                    if result.boxes is None:
                        raise ValueError('A detection model with bounding boxes is required.')
                    boxes = []
                    fire = False
                    for box in result.boxes:
                        label = str(result.names[int(box.cls.item())])
                        score = float(box.conf.item())
                        boxes.append((box.xyxy[0].cpu().tolist(), label, score))
                        fire = fire or label.casefold() in wanted
                    detected_at = time.monotonic()
                    if fire:
                        last_fire_seen[index] = detected_at
                    held_fire = fire or (
                        detected_at - last_fire_seen.get(index, float('-inf'))
                        <= args.fire_hold
                    )
                    with lock:
                        detections[index] = {
                            'captured': captured,
                            'fire': held_fire,
                            'raw_fire': fire,
                            'boxes': boxes,
                        }
                    processed[index] = captured
                    state = 'FIRE' if held_fire else 'CLEAR'
                    if state != last_states.get(index):
                        latency = time.monotonic() - captured
                        print(f'AI camera={index} state={state} '
                              f'batch={inference_seconds:.3f}s latency={latency:.3f}s',
                              flush=True)
                        last_states[index] = state

                stop.wait(0.002)
        except Exception as exc:
            print(f'AI STOPPED: {exc}', flush=True)
            with lock:
                detections.clear()
            stop.set()

    def alarm():
        active = False
        last_sources = None
        alarm_player = None
        alarm_audio_ready = False

        try:
            if not args.alarm_file.is_file():
                raise FileNotFoundError(args.alarm_file)
            alarm_player = WindowsLoopingAudio(
                args.alarm_file,
                args.alarm_volume,
            )
            alarm_audio_ready = True
            print(
                f'Alarm audio ready: {args.alarm_file.resolve()}',
                flush=True,
            )
        except (OSError, ValueError) as exc:
            print(f'Alarm audio unavailable ({exc}); using beep fallback.', flush=True)

        try:
            while not stop.is_set():
                now = time.monotonic()
                with lock:
                    ai_fire = any(
                        index in frames
                        and index in detections
                        and now - frames[index][0] < 2
                        and now - detections[index]['captured'] < 3
                        and detections[index]['fire']
                        for index in cameras
                    )
                    sensor_fire = (
                        pi_sensor['fire']
                        and now - pi_sensor['updated'] < 1.5
                    )
                fire = ai_fire or sensor_fire

                if fire:
                    sources = []
                    if ai_fire:
                        sources.append('CAMERA AI')
                    if sensor_fire:
                        sources.append('PI FLAME SENSOR')
                    source_text = ' + '.join(sources)

                    if not active:
                        print(f'ALARM: {source_text} - sound ON', flush=True)
                        if alarm_audio_ready:
                            # Windows lap vo han den khi trang thai lua ket thuc.
                            alarm_player.play()
                        active = True
                    elif source_text != last_sources:
                        print(f'ALARM source: {source_text}', flush=True)
                    last_sources = source_text

                    if alarm_audio_ready:
                        stop.wait(0.05)
                    elif winsound is not None:
                        try:
                            for beep_index in range(3):
                                winsound.Beep(
                                    args.alarm_frequency,
                                    args.alarm_beep_ms,
                                )
                                if beep_index < 2 and stop.wait(
                                    args.alarm_gap_ms / 1000.0
                                ):
                                    break
                            stop.wait(args.alarm_pause_ms / 1000.0)
                        except RuntimeError:
                            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                            stop.wait(0.85)
                    else:
                        print('\a\a\a', end='', flush=True)
                        stop.wait(0.85)
                else:
                    if active:
                        if alarm_audio_ready:
                            alarm_player.stop()
                        print('ALARM: sound OFF', flush=True)
                        active = False
                        last_sources = None
                    stop.wait(0.05)
        finally:
            if alarm_audio_ready:
                try:
                    alarm_player.stop()
                finally:
                    alarm_player.close()

    class Handler(BaseHTTPRequestHandler):
        def authorized(self):
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode(),
                                       ('Bearer ' + token).encode()):
                self.send_error(401)
                return False
            return True

        def send_status(self):
            data = json.dumps({
                'version': 1,
                'cameras': camera_records(time.monotonic()),
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if not self.authorized():
                return
            if self.path != '/status':
                self.send_error(404)
                return
            self.send_status()

        def do_POST(self):
            if not self.authorized():
                return
            if self.path != '/pi-fire':
                self.send_error(404)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 1024:
                    raise ValueError('invalid body size')
                payload = json.loads(self.rfile.read(length))
                if (
                    not isinstance(payload, dict)
                    or payload.get('version') != 1
                    or type(payload.get('fire')) is not bool
                ):
                    raise ValueError('invalid payload')
            except (ValueError, json.JSONDecodeError):
                self.send_error(400)
                return

            with lock:
                pi_sensor['fire'] = payload['fire']
                pi_sensor['updated'] = time.monotonic()
            self.send_status()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    workers = [threading.Thread(target=capture, args=(i,), daemon=True) for i in cameras]
    workers += [threading.Thread(target=infer, daemon=True),
                threading.Thread(target=server.serve_forever, daemon=True)]
    if not args.mute_alarm:
        workers.append(threading.Thread(target=alarm, daemon=True))
    for worker in workers:
        worker.start()
    print(f'AI on laptop ({args.device}); two-way Pi link on port {args.port}. Q to stop.', flush=True)
    try:
        while not stop.is_set():
            now = time.monotonic()
            for index in cameras:
                with lock:
                    item = frames.get(index)
                    det = detections.get(index)
                online = item is not None and now - item[0] < 2
                view = item[1].copy() if online else np.zeros((480, 640, 3), dtype=np.uint8)
                fresh = online and det is not None and now - det['captured'] < 3
                status = 'UNKNOWN'
                if fresh:
                    status = 'FIRE' if det['fire'] else 'CLEAR'
                    for coords, label, score in det['boxes']:
                        x1, y1, x2, y2 = map(int, coords)
                        cv2.rectangle(view, (x1, y1), (x2, y2), (0, 0, 255), 2)
                        cv2.putText(view, f'{label} {score:.2f}', (x1, max(y1 - 5, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                cv2.putText(view, f'Camera {index}: {status}', (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.imshow(f'FireVisionAI - {index}', view)
            if cv2.waitKey(15) & 0xFF == ord('q'):
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for worker in workers:
            worker.join(timeout=2)
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()

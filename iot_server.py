from aiohttp import web
from picamera2 import Picamera2
import asyncio
from datetime import datetime
import os
import cv2
import numpy as np

# 녹화 설정
RECORD_DIR = "/home/rpm/cctv_recordings"
RECORD_CHUNK = 600  # 10분 단위 분할
RECORD_QUALITY = 23  # H.264 품질 (0=최고, 50=최저)

class VideoRecorder:
    def __init__(self):
        self.is_recording = False
        self.current_writer = None
        self.last_save = datetime.now()
        self.queue = asyncio.Queue(maxsize=30)

    async def start(self):
        self.is_recording = True
        asyncio.create_task(self._write_worker())

    async def stop(self):
        self.is_recording = False
        if self.current_writer:
            self.current_writer.release()
            self.current_writer = None 

    async def _write_worker(self):
        while self.is_recording:
            frame = await self.queue.get()
            if (datetime.now() - self.last_save).seconds >= RECORD_CHUNK:
                self._rotate_writer()
            
            if self.current_writer is None:
                self._create_writer()
            
            self.current_writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    def _create_writer(self):
        if self.current_writer:
            self.current_writer.release()
            self.current_writer = None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{RECORD_DIR}/{timestamp}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*'avc1') 
        self.current_writer = cv2.VideoWriter(
            filename, fourcc, 30, (640, 480), isColor=True
        )

        print('녹화시작: ',filename)
        self.last_save = datetime.now()

    def _rotate_writer(self):
        if self.current_writer:
            self.current_writer.release()
            self.current_writer = None

        self._create_writer()

# 서버 초기화
async def setup_app():
    app = web.Application()
    app['picam2'] = Picamera2()
    app['recorder'] = VideoRecorder()
    
    # 카메라 설정
    config = app['picam2'].create_video_configuration(
        main={"size": (640, 480)},
        encode="main",
        buffer_count=4
    )
    app['picam2'].configure(config)
    app['picam2'].start()

    # 라우트 설정
    app.router.add_get('/', lambda req: web.FileResponse('index.html'))
    app.router.add_get('/stream.mjpg', mjpeg_stream)
    app.router.add_get('/record', record_control)
    
    # 정적 파일 서빙
    # app.router.add_static('/static/', path='static/')

    return app

# MJPEG 스트림 핸들러
async def mjpeg_stream(request):
    response = web.StreamResponse(
        headers={
            'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
            'Cache-Control': 'no-store, must-revalidate',
            'Connection': 'keep-alive'
        }
    )
    await response.prepare(request)
    
    try:
        while True:
            frame = request.app['picam2'].capture_array("main")
            
            # 녹화 활성화 시 프레임 저장
            if request.app['recorder'].is_recording:
                await request.app['recorder'].queue.put(frame.copy())

            # MJPEG 스트림 생성
            ret, jpeg = cv2.imencode('.jpg', frame)
            await response.write(
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + 
                jpeg.tobytes() + b'\r\n'
            )
            await asyncio.sleep(0.033)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        await response.write_eof()
    return response

# 녹화 제어 API
async def record_control(request):
    action = request.query.get('action')
    recorder = request.app['recorder']
    
    if action == 'start':
        await recorder.start()
        return web.Response(text="녹화 시작됨")
    elif action == 'stop':
        await recorder.stop()
        return web.Response(text="녹화 중지됨")
    else:
        return web.Response(text="잘못된 명령", status=400)

if __name__ == '__main__':
    # 저장 폴더 생성
    os.makedirs(RECORD_DIR, exist_ok=True)
    
    # 서버 실행
    app = asyncio.run(setup_app())
    web.run_app(app, host='0.0.0.0', port=5000)

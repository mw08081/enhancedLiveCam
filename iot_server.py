from aiohttp import web
import asyncio
from picamera2 import Picamera2
import io

def init_camera():
    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": (640, 480)},
        buffer_count=4  # 버퍼 최적화
    )
    picam2.configure(config)
    picam2.start()
    return picam2

async def mjpeg_stream(request):
    response = web.StreamResponse(
        status=200,
        headers={
            'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
            'Cache-Control': 'no-store, no-cache, must-revalidate',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*'
        }
    )
    await response.prepare(request)
    
    try:
        while True:
            # JPEG 형식으로 캡처
            stream = io.BytesIO()
            request.app['picam2'].capture_file(stream, format='jpeg')
            jpeg_bytes = stream.getvalue()
            
            # MJPEG 스트림 형식으로 전송
            frame_data = (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(jpeg_bytes)).encode() + b'\r\n\r\n'
                + jpeg_bytes + b'\r\n'
            )

            
            await response.write(frame_data)
            await asyncio.sleep(0.033)  # 30fps
            
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        # 클라이언트 연결 끊김 처리 [2][3]
        pass
    except Exception as e:
        print(f"Stream error: {e}")
    
    return response

async def setup_app():
    app = web.Application()
    app['picam2'] = init_camera()
    
    app.router.add_get('/', lambda req: web.FileResponse('index.html'))
    app.router.add_get('/stream.mjpg', mjpeg_stream)
    
    return app

if __name__ == '__main__':
    app = asyncio.run(setup_app())
    web.run_app(app, host='0.0.0.0', port=5000)

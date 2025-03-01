from PIL import Image, ImageDraw  # requires pip install Pillow
import cv2 as cv  # to be backward compatible with code which may use original opencv
import numpy as np  # requires pip install numpy
import sounddevice as sd  # requires pip installation and installing ffmpeg libraries (sudo apt install ffmpeg etc)
import concurrent.futures
import subprocess
import datetime
import random
import asyncio
import time

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Video stream is a straightforward process of reading frame images received from a URL-like protocol (RTSP, Real-
# Time Streaming Protocol; VBR, Variable Bit Rate) and offloading frame-by-frame to background algorithms doing with
# that data whatever is desired. Machine learning has progressed rapidly enough that large numbers of functionalities
# are now capable of processing at 30 FPS in audio and video, including person detection, object identification, audio
# and video generation; and logical inference algorithms are fast enough to be engaging in near real-time to users,
# meaning that video-aware computer thinking machines are already able to interact with video, or inject itself into.
#
# Numerous public cameras are available online which support direct RTSP, although something weird is going on too. The
# number of public cameras is in the millions, and years ago getting the feed of surf cameras, Bryant Park, Department
# of Transportation cameras, and various warehouse loading docks was relatively straightforward, including without going
# through YouTube or sketching websites that would very probably give you a headache if not malware. I had hoped to use
# those specific sources (surf cameras, National Parks, US Fire Service smoke detection, and Department of Transportation
# Highway cameras) as demonstrations for this example and as recurring use cases, yet they are very hard to find now!
# There are still a sampling of cameras from arouns the world below that are useful enough for this demonstration here.
#
# Generally speaking, purchasing at-home cameras with video and two-way audio is inexpensive and very high quality,
# mostly from the industry of baby monitoring, pet monitoring, and home security; these cameras can be set up easily
# through manufacturer apps that enable seamless streaming, event detection, person and pet monitoring and more. We
# are using Tapo C101 and Tapo C200 (with pan/tilt, and night vision) for under $20 each because these are manufactured
# by TP-Link, one of the original companies of Internet routers and modems. These are easily set up so that each camera
# has a static local IP address, unique login username and password registered onto the device itself, and are invisible
# outside the home router network. From within the home router network, the video and audio stream from the camera can
# be read directly as its own RTSP protocol (i.e., rtsp://username:password@localIP:554/streamID). Each camera provides
# a specific encoding of its audio which can be troublesome and suffers from seconds of latency without coddling the
# setup, but the video is seamless and fast; making the audio latency free is probably more about me than the device.)
# There is one drawback of these devices so far: to send audio to the camera speaker, and to send pan/tilt robotic
# instructions, is straightforward but requires an authentication with the manufacturer cloud system first (i.e., an
# instruction must be sent to Tapo cloud servers, authenticated, then returned to the camera device locked in my home
# network) which violates our principles of in-home entirely-contained traffic, monitoring, and security. We are talking
# with the vendors of Tapo but so far this seems locked in stone: audio broadcast need to go to Tapo computers; why?
# Nonetheless, sending commands to the camera is beyond the scope of this example, and this example can be carried out
# entirely with local IP addresses and RTSP URLs which are identical to those of numerous video cameras on the open web.
#
# There are three processes at work here: the CameraStreaming class is running constantly in the background to load new
# audio and video data into an iterator that a more forward running command is waiting to be filled; for the most part
# you should think of audio and video as two entirely different data sets unified only by a shared timestamp on each.
# For all intents and purposes of the front user the CameraStreaming is delivered with battery included so that you can
# develop on top of the iterator to handle frame-by-frame data before sending your changes of the frame back to the
# visualizer. The CameraStreaming.streaming_video_as_rtsp(rtsp) method call provides a iterator delivering frame-by-
# frame data; in our example we take the frame, run this frame through a real-time process called add_squares_on_image()
# to add white squares randomly on the frame, then submit the frame back to the CameraStreaming through .send() to
# visualize the frame in real-time. This is a blocking sequence meaning that the CameraStreaming gives you a frame and
# waits until you hand the frame back to then visualize and immediate solicit the camera for a new frame; hence the
# real FPS is variable, though quite fast. This simulates a real-time in-line algorithm such as person detection, which
# can easily reach 30 FPS. To handle slower tasks, each frame is added to a global variable buffer, and in the background
# a third run_as_processing_enables() picks up the latest frame and runs a slow-time process (in this example it simply
# waits for five seconds and picks up a new latest frame). This process grabs the latest frame, but allows frames to drop
# in between executions, but can pass global variables back to the up front real-time video processing functions same
# as any other code structure. Finally, in an entire separate background thread is a similar audio stream running and
# playing the inbound audio in half-second chunks. The specific audio_rate of my camera is 8000 which must be specified.
# In the end that is the totality of capturing streaming audio video and presenting back to the monitors annotated data.

# these do not have audio as far as we know; so comment out the line: loop.run_in_executor(run_on_realtime_audio)
rtsp = "http://67.53.46.161:65123/mjpg/video.mjpg"  # Mohouli Park, Hilo, Hawaii
# rtsp = "http://pendelcam.kip.uni-heidelberg.de/mjpg/video.mjpg"  # Kirchhoff Institute for Physics, Germany
# rtsp = "http://webcam01.ecn.purdue.edu/mjpg/video.mjpg"  # Purdue Engineering Mall, USA (this one is boring)
# rtsp = "http://195.196.36.242/mjpg/video.mjpg"  # Soltorget Pajala, Sweden (snow! and ocacsionally people!)
# rtsp = "http://61.211.241.239/nphMotionJpeg?Resolution=320x240&Quality=Standard"  # Tokyo, Japan (a sideview house)
# rtsp = "http://takemotopiano.aa1.netvolante.jp:8190/nphMotionJpeg"  # Osaka, Japan; Takemoto Piano Factory
# rtsp = "http://webcam.mchcares.com/mjpg/video.mjpg"  # San Bernardino, USA; a patio of Community Hospital
#
# you can also search engine "inurl:/mjpg/video.mjpg" to find whatever RTSP local IP addresses people left accidentially
# exposed for whatever reasons; in my quick test there were hundreds and most of them were functional; a fun machine
# learning experiment would play geoguesser on where these are within the world using StreetView style input data too.
# rtsp = http://63.142.190.238:6106/mjpg/video.mjpg  # an unspecified tennis court and parking lot on cycle of cameras


class CameraStreaming:

    @staticmethod
    def streaming_video_as_rtsp(rtsp, add_fps=True):
        cap = cv.VideoCapture(rtsp)
        if not cap.isOpened():
            logger.info("Error: Could not open video stream.")
            exit()

        while True:
            try:
                ret, frame = cap.read()

                if not ret:
                    logger.info("Error: Could not read frame.")
                    break

                tm = cv.TickMeter()  # to monitor clock in background
                tm.start()
                yield frame  # allows user to modify frame; exits into the iterator loop stream

                frame = yield frame  # returns here once other iterator loop calls stream.send()
                if frame is None: continue  # an error likely occurred
                tm.stop()
                if add_fps:
                    cv.putText(frame, f"FPS: {tm.getFPS():.2f}", (0, 45), cv.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255))
                cv.imshow(rtsp, frame)  # in a new frame
                if cv.waitKey(1) & 0xFF == ord('q'):     # Press 'q' to quit
                    break
                tm.reset()

            except Exception as e:
                logger.error(f"an error occurred e={e}")
        cap.release()
        cv.destroyAllWindows()

    @staticmethod
    def streaming_audio_as_rtsp(rtsp, ar=8000, buffer_s=2.0):
        process = None
        try:
            cmd = f'ffmpeg -i {rtsp} -f s16le -'
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True, stderr=subprocess.DEVNULL)
            n_blocks = round(buffer_s*4096/ar)  # approximate number of 4096 byte chunks necessary to be buffer_s length
            while True:  # using 4096 simply so we use a round exponential of 2
                in_bytes = process.stdout.read(4096*n_blocks)
                if not in_bytes:
                    logger.warning("no bytes audio detected")
                    continue
                audio_data = np.frombuffer(in_bytes, np.int16)
                yield audio_data # allows user to modify audio_data; exits into the iterator loop stream

                audio_data = yield audio_data  # returns here once other iterator loop calls stream.send()
                if audio_data is None: continue  # an error likely occurred
                sd.play(audio_data, ar)
                sd.wait()
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait()


buffer = None
def run_as_processing_enables():
    """a simple demonstration for slow-time frame analysis that updates 'as compute is available' for slow processes"""
    # NOTE: the idea here is that most frame analysis cannot be completed within the 1/60 seconds required for real-time
    # analysis; so, a slow-time thread runs in the background to complement the real-time processing, and choices need
    # to be made, i.e., dropping analysis of frames that occur while a frame is already being processed. For instance,
    # person detection (i.e., a bounding box detected that a person is within) and certain object detection (i.e., an
    # object detection algorithm with fewer than about one hundred classes c.f. COCO can operate faster than 1/60 FPS
    # and therefore be detecting every frame. But person identification, which requires searching a database to identify
    # the specific individual within the box, is slower (anywhere from 1/20 second to seconds). Anything slower than
    # real-time will build up forever unless frames are dropped. Yet, there is a lot that can be done: bounding boxes
    # that overlap frame to frame by more than about 0.30 IOU are very probably the same person, etc., meaning that
    # trajectories can be developed quickly, and once a person is identified that augment to the bounding box can be
    # tracked around in real-time as well. A second similar strategy is to simply save the previous e.g., one minute of
    # frames to disk or memory, or all of them, so that information can be processed heavy off-line then integrated in.
    # But the basic structure of multiple concurrent async operators and streaming rtsp are complicated enough to be here.

    global buffer
    while True:
        if buffer is None:
            logger.info("nothing to do in slow-time")
            time.sleep(0.1)
            continue
        try: ts, frame = buffer
        except:
            logger.error("an error occurred in the format of the buffer")
            time.sleep(0.1)
            continue
        try:
            logger.info(f"processing ts={ts}")
            time.sleep(5.0)
        except Exception as e:
            logger.error(f"error={e}")

def add_squares_on_image(nd_array):
    """a simple demonstration for real-time frame analysis and reporting inline to streaming, e.g. object detection"""
    # To see whether you understand this code; you could have run_as_processing_enables() increase a global variable
    # which accounts for the number of n_squares here, instead of generating it randomly, so that every five seconds
    # the number of squares generated increases by one until eventually the entire screen is covered by digital snow.
    # You could also implement this image => ascii method converted which could be fun and we will eventually do, but
    # for the purposes of this example is out of scope so far: https://youtu.be/55iwMYv8tGI?si=ZZUpTr4SsJryOlWG&t=1272
    image = Image.fromarray(nd_array)
    draw = ImageDraw.Draw(image)
    w, h = image.size

    length = 10
    n_squares = random.randint(1, 10)
    for i in range(n_squares):
        x, y = random.uniform(0, w-length), random.uniform(0, h-length)
        draw.rectangle([(x, y), (x+length, y+length)], fill="white")
    return np.array(image)


def run_on_realtime_audio(rtsp):
    # in this exercise we will not amend the audio even in demonstration because simple transformation sound unpleasant
    audio_stream = CameraStreaming.streaming_audio_as_rtsp(rtsp)
    next(audio_stream)  # do not forget this or you will get a None error

    for audio_data in audio_stream:  # request an image from the camera, as a numpy array (WHC: width, height, color)
        audio_stream.send(audio_data)  # send back to player


async def main():
    global buffer

    loop = asyncio.get_running_loop()  # asyncio uses one thread with managed occupancy rather than multiple-threads
    with concurrent.futures.ThreadPoolExecutor() as executor:
        loop.run_in_executor(executor, run_as_processing_enables)  # this establishes a second background thread
        loop.run_in_executor(executor, run_on_realtime_audio, rtsp)  # this establishes a second background thread

        while True:  # there are subtlies to running OpenCV in a background thread; so we run in this foreground here
            video_stream = CameraStreaming.streaming_video_as_rtsp(rtsp)
            next(video_stream)  # do not forget this or you will get a None error

            for frame in video_stream:  # request an image from the camera, as a numpy array (WHC: width, height, color)
                try:
                    now = datetime.datetime.now().isoformat()
                    buffer = [now, frame]  # simply save the immediate frame in a global variable the other thread uses
                    analyzed = add_squares_on_image(frame)
                    video_stream.send(analyzed)  # instead of .send(frame)
                except Exception as e:
                    logger.error(f"frame failed error={e}")

if __name__ == "__main__":
    asyncio.run(main())

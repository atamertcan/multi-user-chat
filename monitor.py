import asyncio
import threading
import json
import os
import functools
import http.server
import socketserver
import websockets

#the monitor page is served from the folder of this file
FOLDER = os.path.dirname(os.path.abspath(__file__))

#http server runs in separate thread
class MonitorHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/" or path == "/monitor.html":
            self.path = "/monitor.html"
            return super().do_GET()
        self.send_error(404)

    #don't print every http request on the console
    def log_message(self, format, *args):
        pass

def start_http_server(host, port):
    handler = functools.partial(MonitorHandler, directory=FOLDER) #to find monitor.html
    try:
        with socketserver.TCPServer((host, port), handler) as httpd:
            print("Monitor page: http://{}:{}".format(host, port))
            httpd.serve_forever()
    except OSError as e:
        print("Could not start the monitor HTTP server: {}".format(e))

#web server runs in an asyncio loop in its own thread
connected = set() #monitoring pages that are connected
loop = None #asyncio loop of the websocket thread
counts = {"users": 0, "messages": 0} #latest numbers

async def ws_handler(websocket):
    connected.add(websocket)
    try:
        await websocket.send(json.dumps(counts)) #show the current numbers right away
        async for message in websocket:
            pass #the page is read-only, anything it sends is ignored
    except Exception:
        pass
    finally:
        connected.remove(websocket)

#send one text to every connected page
async def broadcast(data):
    await asyncio.gather(*(ws.send(data) for ws in list(connected)), return_exceptions=True)

async def start_ws_server(host, port):
    global loop
    try:
        async with websockets.serve(lambda ws: ws_handler(ws), host, port):
            loop = asyncio.get_running_loop()
            print("Monitor WebSocket: ws://{}:{}".format(host, port))
            await asyncio.Future()  # run forever
    except OSError as e:
        print("Could not start the monitor WebSocket server: {}".format(e))

#used by the chat server
#called for every event it only hands the event over to the websocket thread
def send_event(text, users, messages):
    global counts
    counts = {"users": users, "messages": messages}
    if loop is None: #the monitor isn't running
        return
    data = json.dumps({"text": text, "users": users, "messages": messages})
    asyncio.run_coroutine_threadsafe(broadcast(data), loop) #bridge between server thread and broadcast thread

#start both monitoring servers in background threads
def start_monitor(host, http_port, ws_port):
    threading.Thread(target=start_http_server, args=(host, http_port), daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(start_ws_server(host, ws_port)), daemon=True).start()

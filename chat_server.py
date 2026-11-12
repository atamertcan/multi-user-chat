import select
import socket
import pickle
import struct
import argparse
import time
import monitor

SERVER_HOST = 'localhost'
SERVER_PORT = 5000
LOG_FILE = 'chat_server.log'
HTTP_PORT = 8000 #port of the monitoring page
WS_PORT = 8765 #port of the monitoring WebSocket
CLIENT_TIMEOUT = 5 #max seconds a client may stall in the middle of a message
MAX_MESSAGE_SIZE = 4096 #max bytes accepted in one message. mostly enough for long messages
RATE_LIMIT = 5 #message rate limit
RATE_WINDOW = 10 #to measure time
MUTE_TIME = 10 #user will be silenced for 10sec if it hits rate limit


#sending and receiving messages
#Every message is preceded by a length header, so the receiver knows where the message ends
def send(channel, *args):
    buffer = pickle.dumps(args) #convert the message to bytes
    value = socket.htonl(len(buffer)) #length in network byte order
    size = struct.pack("L", value) #length as header bytes
    channel.send(size)
    channel.send(buffer)

#read one message
def receive(channel):
    try:
        size_data = channel.recv(struct.calcsize("L")) #read the header
        size = socket.ntohl(struct.unpack("L", size_data)[0]) #bytes to expect
        if size > MAX_MESSAGE_SIZE: #too big, treat it as bad data
            return None
        buf = b""
        while len(buf) < size:
            chunk = channel.recv(size - len(buf))
            if not chunk:
                return None
            buf += chunk
        return pickle.loads(buf)[0] #bytes back to the message
    except Exception:
        return None

#chat server using select
class ChatServer:
    def __init__(self, host, port, logfile, backlog=5):
        self.clientmap = {} #client socket -> (address, nickname)
        self.logfile = logfile
        self.message_count = 0
        self.ratemap = {} #client socket -> [window start, message count, muted until]
        # Listening socket: only accepts new connections, carries no chat data
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((host, port))
        self.server.listen(backlog)
        print("Server listening on {}:{} ...".format(host, port))

    def timestamp(self):
        return time.strftime("%H:%M:%S")

    #write one line to the log file
    def log(self, kind, details):
        line = "{} | {} | {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), kind, details)
        try:
            with open(self.logfile, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            print("Could not write to the log file: {}".format(e))
        #the same line goes to the monitoring page, with the current numbers
        monitor.send_event(line, len(self.clientmap), self.message_count)

    #send a message separately to every connected user (sender included)
    def broadcast(self, message):
        for client in list(self.clientmap):
            try:
                send(client, message)
            except OSError:
                pass

    #send the current user list to everyone so all clients stay in sync
    def send_user_list(self):
        names = [info[1] for info in self.clientmap.values()]
        self.broadcast('USERS: ' + ','.join(names))

    #return the nickname or nickname + number if it is already taken
    def make_unique(self, nickname):
        taken = [info[1] for info in self.clientmap.values()]
        new_name = nickname
        count = 1
        while new_name in taken:
            new_name = nickname + str(count)
            count += 1
        return new_name

    #tell the client why it was rejected and close the connection
    def reject(self, client, reason):
        print("Rejected registration: {}".format(reason))
        self.log("ERROR", "registration rejected: {}".format(reason))
        try:
            send(client, 'ERROR: ' + reason)
        except OSError:
            pass
        client.close()

    #accept a new connection and process its registration message
    def accept_client(self):
        client, address = self.server.accept()
        #a client that sends nothing must not freeze the whole server
        client.settimeout(CLIENT_TIMEOUT)
        data = receive(client)
        if not isinstance(data, str) or not data.startswith('NAME: '):
            print("Rejected bad registration from {}".format(address))
            self.log("ERROR", "bad registration from {}".format(address))
            client.close()
            return
        nickname = data[len('NAME: '):].strip()
        if nickname == '':
            self.reject(client, 'Nickname cannot be empty')
            return
        #* is reserved for the relay
        if nickname.startswith('*'):
            self.reject(client, 'Nickname cannot start with *')
            return
        if ' ' in nickname or ',' in nickname:
            self.reject(client, 'Nickname cannot contain spaces or commas')
            return
        nickname = self.make_unique(nickname) #add a number if the name is taken
        #tell the client its nickname first, if this fails the client is already gone
        if not self.send_to(client, 'NICK: ' + nickname):
            client.close()
            return
        self.clientmap[client] = (address, nickname) #register the client
        print("Chat server: {} connected from {}".format(nickname, address))
        self.log("CONNECT", "{} {}".format(nickname, address))
        self.broadcast("[{}] * {} joined the chat".format(self.timestamp(), nickname))
        self.send_user_list()

    #remove a client, close its socket and tell the others
    def remove_client(self, sock):
        nickname = self.clientmap.pop(sock)[1] #[1] = nickname in the tuple
        self.ratemap.pop(sock, None) #forget its rate limit record
        sock.close()
        print("Chat server: {} disconnected".format(nickname))
        self.log("DISCONNECT", nickname)
        self.broadcast("[{}] * {} left the chat".format(self.timestamp(), nickname))
        self.send_user_list()

    #checks rate limit for each user message, return True if the user may send a message now, False if it is rate limited
    def check_rate_limit(self, sock):
        nickname = self.clientmap[sock][1]
        now = time.time()
        if sock not in self.ratemap: #first message of this user
            self.ratemap[sock] = [now, 0, 0]
        record = self.ratemap[sock]
        if now < record[2]: #still muted, tell the user how long
            left = int(record[2] - now) + 1
            self.send_to(sock, "[{}] * You are muted, try again in {} seconds".format(self.timestamp(), left))
            return False
        if now - record[0] >= RATE_WINDOW: #the old window is over, start a new one
            record[0] = now
            record[1] = 0
        record[1] += 1
        if record[1] > RATE_LIMIT: #too many messages in this window, mute the user
            record[0] = now + MUTE_TIME #a fresh window starts when the mute ends
            record[1] = 0
            record[2] = now + MUTE_TIME
            self.send_to(sock, "[{}] * Rate limit exceeded (max {} messages in {} seconds), you are muted for {} seconds".format(self.timestamp(), RATE_LIMIT, RATE_WINDOW, MUTE_TIME))
            self.log("RATE_LIMIT", "{} muted for {} seconds (more than {} messages in {} seconds)".format(nickname, MUTE_TIME, RATE_LIMIT, RATE_WINDOW))
            return False
        return True

    #handle a message coming from a registered client
    def handle_client(self, sock):
        data = receive(sock)
        if data is None: #connection lost or bad data
            self.remove_client(sock)
            return
        nickname = self.clientmap[sock][1]
        #public and private messages are rate limited per user
        if isinstance(data, str) and (data.startswith('PUBLIC: ') or data.startswith('PRIVATE: ')):
            if not self.check_rate_limit(sock):
                return
        if isinstance(data, str) and data.startswith('PUBLIC: '):
            text = data[len('PUBLIC: '):]
            if text.strip() == '':
                self.send_to(sock, "[{}] * Error: message text cannot be empty".format(self.timestamp()))
                self.log("ERROR", "empty message from {}".format(nickname))
            else:
                self.broadcast("[{}] {}: {}".format(self.timestamp(), nickname, text))
                self.message_count += 1 #counted once, however many users receive it
                self.log("PUBLIC", "{} -> ALL | {}".format(nickname, text))
        elif isinstance(data, str) and data.startswith('PRIVATE: '):
            self.handle_private(sock, data[len('PRIVATE: '):])
        else: #unknown message type
            self.send_to(sock, "[{}] * Error: unknown message type".format(self.timestamp()))
            self.log("ERROR", "unknown message type from {}".format(nickname))

    #send a message to one client only
    #we're defining new func for send becuase we need to know if delivery has been done, send func won't ensures this
    #it returns true if it delivers successfully otherwise we get false, we use these situations
    def send_to(self, sock, message):
        try:
            send(sock, message)
            return True
        except OSError:
            return False

    #deliver a private message only to the recipient
    def handle_private(self, sock, content):
        sender = self.clientmap[sock][1]
        parts = content.split(' ', 1) #split it at first space
        if len(parts) < 2 or parts[1].strip() == '':
            self.send_to(sock, "[{}] * Usage: /msg nickname message".format(self.timestamp()))
            self.log("ERROR", "invalid private message format from {}".format(sender))
            return
        target_name = parts[0]
        text = parts[1].strip()
        #find the recipient's socket by nickname
        target = None
        for client, info in self.clientmap.items():
            if info[1] == target_name:
                target = client
        if target is None:
            self.send_to(sock, "[{}] * Error: user '{}' is not connected".format(self.timestamp(), target_name))
            self.log("ERROR", "private message from {} failed, {} is not connected".format(sender, target_name))
            return
        receiver = self.clientmap[target][1] #to get real nickname
        if self.send_to(target, "[{}] [PRIVATE] {}: {}".format(self.timestamp(), sender, text)):
            self.send_to(sock, "[{}] [PRIVATE] you -> {}: {}".format(self.timestamp(), receiver, text))
            self.message_count += 1 #only delivered messages are counted
            self.log("PRIVATE", "{} -> {} | {}".format(sender, receiver, text))
        else:
            self.send_to(sock, "[{}] * Error: could not deliver the message to '{}'".format(self.timestamp(), receiver))
            self.log("ERROR", "private message from {} to {} could not be delivered".format(sender, receiver))

    #handle whichever socket has data
    def run(self):
        try:
            while True:
                #sockets to watch: the listening socket + all connected clients
                inputs = [self.server] + list(self.clientmap)
                #wait for sockets with data. 1s timeout
                readable, writeable, exceptional = select.select(inputs, [], [], 1.0)
                #try-except for each socket
                for sock in readable:
                    try:
                        if sock == self.server:
                            self.accept_client() #someone wants to connect
                        else:
                            self.handle_client(sock) #client sent a message
                    except Exception as e:
                        #an unexpected error caused by one client must not stop the server
                        print("Error: {}".format(e))
                        self.log("ERROR", "unexpected error: {}".format(e))
                        if sock in self.clientmap:
                            self.remove_client(sock)
        except KeyboardInterrupt:
            print("\nShutting down server...")
        finally:
            #close every socket on exit
            for sock in list(self.clientmap):
                sock.close()
            self.server.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Chat Server')
    parser.add_argument('--host', default=SERVER_HOST, help='IP address to listen on')
    parser.add_argument('--port', type=int, default=SERVER_PORT, help='TCP chat port')
    parser.add_argument('--log', default=LOG_FILE, help='log file')
    parser.add_argument('--http-port', type=int, default=HTTP_PORT, help='monitoring page (HTTP) port')
    parser.add_argument('--ws-port', type=int, default=WS_PORT, help='monitoring WebSocket port')
    args = parser.parse_args()

    monitor.start_monitor(args.host, args.http_port, args.ws_port) #runs in separate threads
    server = ChatServer(args.host, args.port, args.log)
    server.run()

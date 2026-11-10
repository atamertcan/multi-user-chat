import select
import socket
import pickle
import struct
import argparse
import time

SERVER_HOST = 'localhost'
SERVER_PORT = 5000
CLIENT_TIMEOUT = 5          #max seconds a client may stall in the middle of a message


#sending and receiving messages
#Every message is preceded by a length header, so the receiver knows where the message ends
def send(channel, *args):
    buffer = pickle.dumps(args)              # convert the message to bytes
    value = socket.htonl(len(buffer))        # length in network byte order
    size = struct.pack("L", value)           # length as header bytes
    channel.send(size)
    channel.send(buffer)

#read one message. Return None if the connection is lost or data is bad
def receive(channel):
    try:
        size_data = channel.recv(struct.calcsize("L"))           #read the header
        size = socket.ntohl(struct.unpack("L", size_data)[0])    #bytes to expect
        buf = b""
        while len(buf) < size:
            chunk = channel.recv(size - len(buf))
            if not chunk:
                return None
            buf += chunk
        return pickle.loads(buf)[0]                  #bytes back to the message
    except Exception:
        return None

#chat server using select
class ChatServer:
    def __init__(self, host, port, backlog=5):
        self.clientmap = {}   #client socket -> (address, nickname)
        # Listening socket: only accepts new connections, carries no chat data
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((host, port))
        self.server.listen(backlog)
        print("Server listening on {}:{} ...".format(host, port))

    def timestamp(self):
        return time.strftime("%H:%M:%S")

    #send a message separately to every connected user (sender included)
    def broadcast(self, message):
        for client in list(self.clientmap):
            try:
                send(client, message)
            except OSError:
                pass

    #accept a new connection and process its registration message
    def accept_client(self):
        client, address = self.server.accept()
        # A client that sends nothing must not freeze the whole server
        client.settimeout(CLIENT_TIMEOUT)
        data = receive(client)
        if not isinstance(data, str) or not data.startswith('NAME: '):
            print("Rejected bad registration from {}".format(address))
            client.close()
            return
        nickname = data[len('NAME: '):].strip()
        if nickname == '':
            client.close()
            return
        self.clientmap[client] = (address, nickname)    #register the client
        print("Chat server: {} connected from {}".format(nickname, address))
        send(client, 'NICK: ' + nickname)
        self.broadcast("[{}] * {} joined the chat".format(self.timestamp(), nickname))

    #remove a client, close its socket and tell the others
    def remove_client(self, sock):
        nickname = self.clientmap.pop(sock)[1]   #[1] = nickname in the tuple
        sock.close()
        print("Chat server: {} disconnected".format(nickname))
        self.broadcast("[{}] * {} left the chat".format(self.timestamp(), nickname))

    #handle a message coming from a registered client
    def handle_client(self, sock):
        data = receive(sock)
        if data is None:               #connection lost or bad data
            self.remove_client(sock)
            return
        if isinstance(data, str) and data.startswith('PUBLIC: '):
            text = data[len('PUBLIC: '):]
            nickname = self.clientmap[sock][1]
            self.broadcast("[{}] {}: {}".format(self.timestamp(), nickname, text))

    #handle whichever socket has data
    def run(self):
        try:
            while True:
                #sockets to watch: the listening socket + all connected clients
                inputs = [self.server] + list(self.clientmap)
                #wait for sockets with data. 1s timeout
                readable, writeable, exceptional = select.select(inputs, [], [], 1.0)
                for sock in readable:
                    if sock == self.server:
                        self.accept_client()       #someone wants to connect
                    else:
                        self.handle_client(sock)   #client sent a message
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
    args = parser.parse_args()

    server = ChatServer(args.host, args.port)
    server.run()

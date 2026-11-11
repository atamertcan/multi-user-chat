import select
import socket
import pickle
import struct
import argparse
import time

SERVER_HOST = 'localhost'
SERVER_PORT = 5000
CLIENT_TIMEOUT = 5 #max seconds a client may stall in the middle of a message


#sending and receiving messages
#Every message is preceded by a length header, so the receiver knows where the message ends
def send(channel, *args):
    buffer = pickle.dumps(args) #convert the message to bytes
    value = socket.htonl(len(buffer)) #length in network byte order
    size = struct.pack("L", value) #length as header bytes
    channel.send(size)
    channel.send(buffer)

#read one message. Return None if the connection is lost or data is bad
def receive(channel):
    try:
        size_data = channel.recv(struct.calcsize("L")) #read the header
        size = socket.ntohl(struct.unpack("L", size_data)[0]) #bytes to expect
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
    def __init__(self, host, port, backlog=5):
        self.clientmap = {} #client socket -> (address, nickname)
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
        self.clientmap[client] = (address, nickname) #register the client
        print("Chat server: {} connected from {}".format(nickname, address))
        send(client, 'NICK: ' + nickname)
        self.broadcast("[{}] * {} joined the chat".format(self.timestamp(), nickname))
        self.send_user_list()

    #remove a client, close its socket and tell the others
    def remove_client(self, sock):
        nickname = self.clientmap.pop(sock)[1] #[1] = nickname in the tuple
        sock.close()
        print("Chat server: {} disconnected".format(nickname))
        self.broadcast("[{}] * {} left the chat".format(self.timestamp(), nickname))
        self.send_user_list()

    #handle a message coming from a registered client
    def handle_client(self, sock):
        data = receive(sock)
        if data is None: #connection lost or bad data
            self.remove_client(sock)
            return
        if isinstance(data, str) and data.startswith('PUBLIC: '):
            text = data[len('PUBLIC: '):]
            nickname = self.clientmap[sock][1]
            self.broadcast("[{}] {}: {}".format(self.timestamp(), nickname, text))
        elif isinstance(data, str) and data.startswith('PRIVATE: '):
            self.handle_private(sock, data[len('PRIVATE: '):])

    #send a message to one client only
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
            return
        receiver = self.clientmap[target][1] #to get real nickname
        if self.send_to(target, "[{}] [PRIVATE] {}: {}".format(self.timestamp(), sender, text)):
            self.send_to(sock, "[{}] [PRIVATE] you -> {}: {}".format(self.timestamp(), receiver, text))
        else:
            self.send_to(sock, "[{}] * Error: could not deliver the message to '{}'".format(self.timestamp(), receiver))

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
                        self.accept_client() #someone wants to connect
                    else:
                        self.handle_client(sock) #client sent a message
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

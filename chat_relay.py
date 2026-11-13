#chat relay: sits between a chat client and the chat server and adds a * in front of the nickname
#based on the course example 06-proxy-Proxy.py
import socket
import pickle
import struct
import argparse
import threading

RELAY_HOST = 'localhost'
RELAY_PORT = 6000 #port where the chat clients connect
SERVER_HOST = 'localhost'
SERVER_PORT = 5001 #relay port of the chat server
MAX_MESSAGE_SIZE = 4096 #max bytes accepted in the registration message


#sending and receiving messages (same as in the chat server)
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

#tell the client why it was rejected and close the connection
def reject(client, reason):
    try:
        send(client, 'ERROR: ' + reason)
    except OSError:
        pass
    client.close()

#close both sides of a connection
def close_both(a, b):
    for s in (a, b):
        try:
            s.shutdown(socket.SHUT_RDWR) #wakes up the thread that is waiting on this socket
        except OSError:
            pass
        s.close()

#pass data from one side to the other we won't change anything for now
def forward(source, target):
    try:
        while True:
            data = source.recv(4096)
            if not data:
                break
            target.sendall(data)
    except OSError:
        pass
    close_both(source, target) #if one side closes, the other side is closed too

#handle one chat client (runs in its own thread)
def handle_client(client, server_host, server_port):
    #client that sends nothing must not wait forever
    client.settimeout(5)
    data = receive(client) #registration message: "NAME: ata"
    if not isinstance(data, str) or not data.startswith('NAME: '):
        client.close()
        return
    nickname = data[len('NAME: '):].strip()
    if nickname == '':
        reject(client, 'Nickname cannot be empty')
        return
    #client cannot choose a name starting with * only the relay adds it
    if nickname.startswith('*'):
        reject(client, 'Nickname cannot start with *')
        return
    #open the connection to the chat server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.connect((server_host, server_port))
        #add exactly one * and pass the registration on to the chat server
        send(server, 'NAME: *' + nickname)
    except OSError:
        server.close()
        reject(client, 'The chat server is not available')
        return
    #from now on everything is passed unchanged in both directions
    #the chat server's answer (the assigned nickname) also goes to the client this way
    client.settimeout(None)
    threading.Thread(target=forward, args=(client, server), daemon=True).start()
    threading.Thread(target=forward, args=(server, client), daemon=True).start()

def start_relay(host, port, server_host, server_port):
    #create a TCP socket for the relay
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, port))
        s.listen(5)
        s.settimeout(1.0) #ctrl+c works
        print("Relay listening on {}:{}, chat server relay port is {}:{}".format(host, port, server_host, server_port))
        try:
            while True:
                try:
                    client, addr = s.accept()
                except socket.timeout:
                    continue
                print("Relay accepted connection from {}".format(addr))
                #handle each client in a separate thread
                threading.Thread(target=handle_client, args=(client, server_host, server_port), daemon=True).start()
        except KeyboardInterrupt:
            print("\nRelay stopped")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Chat Relay')
    parser.add_argument('--host', default=RELAY_HOST, help='address the relay listens on')
    parser.add_argument('--port', type=int, default=RELAY_PORT, help='port where the chat clients connect')
    parser.add_argument('--server-host', default=SERVER_HOST, help='address of the chat server')
    parser.add_argument('--server-port', type=int, default=SERVER_PORT, help='relay port of the chat server')
    args = parser.parse_args()

    start_relay(args.host, args.port, args.server_host, args.server_port)

# python chat_relay.py --port=6000 --server-port=5001

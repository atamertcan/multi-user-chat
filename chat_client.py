import socket
import sys
import pickle
import struct
import argparse
import threading

SERVER_HOST = 'localhost'
SERVER_PORT = 5000


#sending and receiving messages
def send(channel, *args):
    buffer = pickle.dumps(args) #convert the message to bytes
    value = socket.htonl(len(buffer)) #length in network byte order
    size = struct.pack("L", value) #length as header bytes
    channel.send(size)
    channel.send(buffer)

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
        return pickle.loads(buf)[0]                  #bytes back to the message
    except Exception:
        return None

#command line chat client using a separate input thread
class ChatClient:
    def __init__(self, name, host, port):
        self.connected = False
        self.users = [] #current user list, kept up to date by the server
        #connect to the server and send the registration message
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, port))
            send(self.sock, 'NAME: ' + name)
        except socket.error:
            print("Failed to connect to chat server @ {}:{}".format(host, port))
            sys.exit(1)
        #wait for the server's answer
        data = receive(self.sock)
        #the server rejected our nickname, show the reason and quit
        if isinstance(data, str) and data.startswith('ERROR: '):
            print("Registration failed: " + data[len('ERROR: '):])
            self.sock.close()
            sys.exit(1)
        if not isinstance(data, str) or not data.startswith('NICK: '):
            print("Registration failed.")
            self.sock.close()
            sys.exit(1)
        #server may have changed our nickname, so use the one it assigned
        self.name = data[len('NICK: '):]
        if self.name != name.strip():
            print("Nickname '{}' was changed by the server, you are '{}'".format(name.strip(), self.name))
        self.prompt = '[' + self.name + ']> '
        self.connected = True
        print("Now connected to chat server @ {}:{} as {}".format(host, port, self.name))

#two threads: the input thread sends, the main thread receives.
    def run(self):
        def input_thread():
            #reads the keyboard and sends what the user types
            while self.connected:
                line = sys.stdin.readline()
                if line == '' or line.strip() == '/exit':
                    self.connected = False
                    self.sock.close()
                    break
                line = line.strip()
                if line == '/users':
                    print("Users online ({}): {}".format(len(self.users), ', '.join(self.users)))
                    sys.stdout.write(self.prompt)
                    sys.stdout.flush()
                elif line == '/msg' or line.startswith('/msg '):
                    #/msg nickname message -> sent as "PRIVATE: nickname message"
                    parts = line[len('/msg '):].strip().split(' ', 1)
                    if len(parts) < 2 or parts[1].strip() == '':
                        print("Usage: /msg nickname message")
                        sys.stdout.write(self.prompt)
                        sys.stdout.flush()
                    else:
                        try:
                            send(self.sock, 'PRIVATE: ' + parts[0] + ' ' + parts[1].strip())
                        except OSError:
                            break
                elif line:
                    try:
                        send(self.sock, 'PUBLIC: ' + line)   #send as a public message
                    except OSError:
                        break

        #start the input thread. daemon=True: it stops when the main program ends
        t = threading.Thread(target=input_thread, daemon=True)
        t.start()

        try:
            #keeps listening for everything the server sends
            while self.connected:
                data = receive(self.sock)
                if data is None:
                    if self.connected:
                        print("\nConnection to the server was lost.")
                    break
                #user list updates are stored, not printed
                if isinstance(data, str) and data.startswith('USERS: '):
                    self.users = data[len('USERS: '):].split(',')
                    continue
                print("\n" + str(data))
                sys.stdout.write(self.prompt)
                sys.stdout.flush()
        except KeyboardInterrupt:
            print("Client interrupted.")
        finally:
            self.connected = False
            self.sock.close()
            print("Client shutting down.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Chat Client')
    parser.add_argument('--name', default=None, help='nickname')
    parser.add_argument('--host', default=SERVER_HOST, help='server address')
    parser.add_argument('--port', type=int, default=SERVER_PORT, help='server port')
    args = parser.parse_args()

    name = args.name
    if not name:
        name = input("Nickname: ").strip()
    client = ChatClient(name, args.host, args.port)
    client.run()

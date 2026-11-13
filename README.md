# Multi-User Chat System

Python TCP clients chat through a TCP server with public and private messages. A browser page shows what happens on the server live (HTTP + WebSocket). An optional relay sits between a client and the server.


## Files

| File | Purpose |
|---|---|
| `chat_server.py` | Chat server (TCP, `select`). Also starts the monitoring page. |
| `chat_client.py` | Console chat client. |
| `chat_relay.py` | Optional relay, adds a `*` prefix to nicknames. |
| `monitor.py`, `monitor.html` | Monitoring page: HTTP server, WebSocket server and the page itself. |
| `requirements.txt` | Dependencies. |
| `test_evidence/` | Test screenshots and their explanation ([test_explanation.md](test_evidence/test_explanation.md)). |

## Installation

Python 3.11 or newer is required (tested with Python 3.13.7 on Windows 11). The only dependency is `websockets==17.4`
(everything else is the standard library).

```bash
python -m venv venv
```
```bash
venv\Scripts\activate
```
```bash
pip install -r requirements.txt
```

## Running

Startup order: server, then (optionally) the relay, then the clients, then the browser.
Every command runs in its own terminal, from the project folder.

**1. Server**
```bash
python chat_server.py
```

**2. Relay (optional)**
```bash
python chat_relay.py
```

**3. Clients** (one terminal each)
```bash
python chat_client.py --name=ali
```
```bash
python chat_client.py --name=veli
```
Through the relay (see "Relay" below):
```bash
python chat_client.py --name=burak --port=6000
```

**4. Monitoring page:** open http://localhost:8000 in a browser.

### Options

| Program | Option | Default | Meaning |
|---|---|---|---|
| server | `--host` | `localhost` | Address to listen on (for all chat and monitoring ports) |
| server | `--port` | `5000` | Chat port (direct clients) |
| server | `--relay-port` | `5001` | Port for the relay |
| server | `--http-port` | `8000` | Monitoring page (HTTP) |
| server | `--ws-port` | `8765` | Monitoring WebSocket |
| server | `--log` | `chat_server.log` | Log file |
| client | `--name` | asked if missing | Nickname |
| client | `--host`, `--port` | `localhost`, `5000` | Server (or relay) address |
| relay | `--host`, `--port` | `localhost`, `6000` | Where clients connect to the relay |
| relay | `--server-host`, `--server-port` | `localhost`, `5001` | Relay port of the chat server |

If the monitoring ports are changed, open the page with the WebSocket port in the address:
`http://localhost:9000/?ws=9001`.

### Client commands

| Input | Effect |
|---|---|
| `hello everyone` | Public message to all users |
| `/msg nickname text` | Private message, only the recipient gets it |
| `/users` | Show the connected users |
| `/exit` | Leave the chat |

### Monitoring page

Read-only page. It shows the number of chat users, the number of processed messages and a live list of events
(connections, disconnections, public and private messages, errors, rate limit events). Only events after the page was
opened are shown. The page is not a chat user. Closing it does not affect the chat.

### Relay

`chat_relay.py` listens on port 6000. For every client it opens a connection to the relay port (5001) of the chat server.
A client that connects through the relay gets a `*` in front of its nickname (`burak` becomes `*burak`),
a client that connects directly never has one. Authentication is not used.

## Design notes

### Message format and framing

TCP has no message boundaries, so every message is sent as a **length header** (`struct` format `L`, 4 bytes on Windows, network byte order) followed by
the message. The message is a Python `str` serialized with `pickle`, so text is Unicode; the log file is written as UTF-8.
The receiver reads the header, then reads exactly that many bytes (a loop handles messages that arrive in pieces).
The **maximum accepted message size is 4096 bytes**, a larger message is treated as bad data and the connection is closed.
`pickle` is only meant for trusted clients.

The text of the messages has the form `TYPE: content`:

| Direction | Message | Meaning |
|---|---|---|
| client to server | `NAME: ali` | Registration (first message) |
| server to client | `NICK: ali1` | Assigned nickname |
| server to client | `ERROR: reason` | Registration rejected |
| client to server | `PUBLIC: text` | Public message |
| client to server | `PRIVATE: nickname text` | Private message |
| server to client | `USERS: ali,veli` | User list, sent on every join and leave |
| server to client | `[12:00:00] ali: text` | Public message with server timestamp and sender |
| server to client | `[12:00:00] [PRIVATE] ali: text` | Private message, `[PRIVATE] you -> veli: text` as confirmation |

The sender of a message is taken from the server's own record of the connection, never from the message.
Public messages are sent separately to every connected user (sender included) over its own TCP connection.
Unknown message types, empty messages, wrong data and unknown recipients get an error message or are rejected,
they never stop the server. A private message to a user who is not connected returns an error and is not stored.

### Concurrency model

- **Server:** one thread. `select` watches the chat port, the relay port and all client sockets. Nicknames, counters
  and log writes are only touched by this thread, so no locks are needed. A client that stops sending in the middle of a message
  is dropped after 5 seconds.
- **Client:** two threads. The main thread receives, an input thread reads the keyboard and sends, so messages arrive
  while the user is typing.
- **Relay:** one thread for each client during registration, then two threads per client (client to server and
  server to client). If one side closes, both sockets are closed.
- **Monitoring:** HTTP server in a thread, WebSocket server (asyncio) in another thread. The chat server passes each
  event to the WebSocket thread without waiting for it.

### Nicknames

- Unique among the connected users. If a name is taken a number is added (`ali` becomes `ali1`) and the assigned name
  is returned to the client.
- Spaces and commas are not allowed (they would break `/msg` and the user list). Empty names are rejected.
- Names starting with `*` are reserved for the relay: direct clients are rejected, the relay port of the server accepts
  only names that start with `*`. If a relayed name is taken, the number is added at the end (`*ali1`).

### Rate limiting

Per user (per connection, not per IP or relay): **at most 5 public/private messages in 10 seconds** (fixed 10 second window).
Above that the user is **muted for 10 seconds**, is told why, and the event is logged. Messages sent while muted are not
processed and not counted.

### Logging and counters

`chat_server.log` is created in the folder where the server was started (option `--log`). It is written as UTF-8, one line
per event: `date time | TYPE | details`. Types: `CONNECT`, `DISCONNECT`, `PUBLIC`, `PRIVATE`, `ERROR`, `RATE_LIMIT`.
The same lines are sent to the monitoring page.

- *Chat users*: users that are connected now.
- *Processed messages*: each delivered public or private message counts once, however many users receive it.
  Rejected messages, failed private messages and system events (join, leave, user list) are not counted.

### Known limits

- Messages larger than 4096 bytes are not accepted.
- The length header is read with one `recv` call, which is fine on `localhost` but not guaranteed on a real network.
- `pickle` must not be used with untrusted clients.

## Tests

Manual tests for T01-T07 with screenshots: [test_evidence/test_explanation.md](test_evidence/test_explanation.md).

# Basic functional tests

Manual tests T01-T07, run on one computer (`localhost`). Screenshots are in this folder.
The nicknames in the screenshots (ata, egemen, ece, ...) are just test names.

## T01 - Public chat
Public messages reach every client with a timestamp and the sender's nickname. `/users` shows the user list.

![T01](t01_t04a_public_users_exit.png)

## T02 - Private chat
A private message reaches only the recipient, the third client sees nothing. Messaging a nickname that is not connected returns an error.

![T02](t02_private_chat.png)

## T03 - Nicknames
A name that is already taken gets a different one (`ata1`). A name starting with `*` is rejected.

![T03](t03_nicknames.png)

## T04 - Disconnection
`/exit` (first screenshot above) and closing the client window both remove the user from the list, the others are notified and the server keeps running.

![T04](t04b_window_closed.png)

## T05 - Rate limiting
More than 5 messages in 10 seconds mutes the user for 10 seconds, the user is told why.

![T05](t05_rate_limit.png)

## T06 - Logs and live monitoring
Events appear on the monitoring page without a refresh, with the user count and the processed message count.

![T06 live](t06a_monitor_live_events.png)

Later in the same session. A message sent to several users is counted once.

![T06 counts](t06b_monitor_counts_after.png)

The chat keeps working after the monitoring page is closed.

![T06 page closed](t06c_chat_after_page_closed.png)

The log file (`chat_server.log`).

![T06 log](t06d_log_file.png)

## T07 - Relay (optional)
A client connected through the relay gets the `*` prefix (`*burak`), chats with a directly connected client and its exit is cleaned up.

![T07](t07_relay.png)

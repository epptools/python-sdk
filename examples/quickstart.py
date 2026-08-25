"""Minimal end-to-end example. Requires a live endpoint + credentials.

    python examples/quickstart.py
"""

import logging
import os
import sys
from pathlib import Path

# Run from a clone without installing: make the package importable. Splitting the path on the
# literal "examples" broke as soon as the checkout itself sat under a directory of that name.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from epptools import Client, Config
from epptools.exceptions import CommandException, EppException

logging.basicConfig(level=logging.INFO)

config = Config(
    host="epp.registry.example",
    clid="EXAMPLE",
    password="your-secret",
    port=700,             # default; override only if the endpoint moves
    lang="uk",            # localized result messages (en | uk | ua | ru)
    # Port 700 presents a certificate from the registry's OWN private CA, so the CA bundle is
    # REQUIRED — without it the handshake fails verification.
    ca_file=os.environ.get("EPP_CA", "/path/to/registry-ca.pem"),
)

client = Client(config, logger=logging.getLogger("epp"))
try:
    client.connect()      # TLS + read <greeting>
    client.login()

    avail = client.domain.check(["example.com.ua"]).availability()
    print("availability:", avail)

    info = client.domain.info("example.com.ua")
    print("exDate:", info.value("exDate"))

    bal = client.balance().balance()
    print("balance:", bal)

    msg = client.poll.request()
    if msg.message_id() is not None:
        # queue_message() is the NOTICE text. message() is the result banner ("ack to dequeue"),
        # identical on every poll reply — printing that and then acking destroys the unread
        # notice at the registry for good.
        print("poll:", msg.queue_date(), msg.queue_message())
        client.poll.ack(msg.message_id())

    client.logout()
except CommandException as exc:
    print("EPP error %d: %s" % (exc.epp_code, exc))
except EppException as exc:
    print("SDK error:", exc)
finally:
    client.disconnect()





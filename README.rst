Stamp rally
===========

This is a plugin for `pretix`_ that runs a stamp rally by scanning attendee ticket QR codes.

Each booth opens a scanner page on a phone. When an attendee visits, staff scan the QR code
on the ticket. That visit is stored as a stamp. After the required number of booths, the
attendee has completed the rally.

This is independent of entrance check-in. Main-door check-in lists keep working as usual.

Features
--------

* Booths with their own scanner links (no pretix account needed at the booth)
* Camera or hardware scanner / typed ticket code
* Duplicate scans at the same booth are shown as already collected
* Configurable number of booths required to finish (or all booths)
* Progress list in the backend and on the order page
* Attendee name and email stored with each scan
* Booth-by-booth view of who was scanned, with partial and complete (all booths) filters for a raffle
* CSV / Excel export of that list
* Raffle draw from complete, partial, or all scanned tickets, with a slot-machine screen that stops on the winner’s name and order code
* Data shredder for GDPR deletion

Setup
-----

1. Install the plugin into your pretix environment::

     pip install -e /path/to/pretix-stamp-rally

2. Restart pretix.

3. Enable **Stamp rally** on the event **Plugins** tab.

4. Open **Stamp rally → Booths** and create one booth per station.

5. Open each booth and give the scanner link to that booth’s phone.

6. Optionally set how many booths are required under **Stamp rally → Settings**.

Development
-----------

1. Use a working `pretix development setup`_.

2. ``pip install -e .`` inside this repository.

3. Restart pretix and enable the plugin on an event.

License
-------

Copyright 2026 ITSIP Travel

Released under the terms of the Apache License 2.0

.. _pretix: https://github.com/pretix/pretix
.. _pretix development setup: https://docs.pretix.eu/en/latest/development/setup.html

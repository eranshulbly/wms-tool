# -*- encoding: utf-8 -*-
"""Order tracking — a read-only view of where an order has been.

Owns no tables and writes nothing. Everything it reports already exists:
potential_order for the status and box count, order_state_history for who moved
it and when, order_picklist for the sheet and the picker card, dealer for the
name. This module is the join, nothing more.

It exists because that story was only assemblable by someone with a database
client. The floor's question — "who picked this, when, how many boxes, is it
gone yet" — had no screen.
"""

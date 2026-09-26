# -*- encoding: utf-8 -*-
"""diagnostics module — what the handheld reports about itself.

A sideloaded handset is otherwise opaque: no adb, no log a warehouse operator can
read out, and a refused install leaves the previous build in place looking exactly
like a successful one. This gives the device a way to say which build it is
running, who is signed in, what it sees on screen and what failed — so a problem
can be diagnosed from the server instead of over a phone call.

Deliberately temporary. See schema.py for the retention cap and router_v1.py for
the switch that turns it off.
"""

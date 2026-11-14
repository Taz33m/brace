"""Matterport's six open problems, each taken as far as it honestly goes in a weekend.

Each module is self-contained: it reads the sponsor data Brace already caches, writes its result under
data/cache/open/<name>/, and exposes one function the app can call. Nothing here is imported by the
planner or the server until the lead wires it in.
"""

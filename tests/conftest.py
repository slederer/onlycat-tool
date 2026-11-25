import os

# /projects probes every side-project host in the background. Tests must not
# touch the network, so the probe is off; tests set statuses directly.
os.environ.setdefault("PROJECT_STATUS_PROBE", "0")

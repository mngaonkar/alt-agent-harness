# Sample process RSS over time to distinguish a leak from normal churn.
# args: {"samples": int (default 5), "interval_s": float (default 0.4)}
import resource
import sys
import time

samples = int(args.get("samples", 5))
interval = float(args.get("interval_s", 0.4))
unit = "kb" if sys.platform.startswith("linux") else "bytes"

readings = []
for i in range(max(2, min(samples, 20))):
    readings.append(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if i < samples - 1:
        time.sleep(interval)

drift = readings[-1] - readings[0]
print("samples (%s): %s" % (unit, readings))
print("drift over window   : %+d %s" % (drift, unit))

# ru_maxrss is a high-water mark, so it should not fall. Growth of a few
# pages is noise; tens of MB over a short window is interesting.
threshold = 20 * 1024 * 1024 if unit == "bytes" else 20 * 1024
result = {
    "readings": readings,
    "unit": unit,
    "drift": drift,
    "min": min(readings),
    "max": max(readings),
    "verdict": "growing" if drift > threshold else "stable",
}

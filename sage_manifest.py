# Client for the Sage node-manifest endpoint.
#
# This is the authoritative roster of each node's compute hosts (and sensors),
# the same source the Sage portal uses to label rpi / rpi.lorawan / nxcore /
# nxagent rows on its status tooltip. We join it to sage_data_client uptime
# data by serial number to report last-seen PER ROLE (see coverage_utils).
#
# Shape confirmed against a live call to .../nodes/W099/ (2026-06): the
# single-node endpoint returns the node object DIRECTLY (a dict), and the
# all-nodes endpoint returns a LIST of such dicts. Each compute entry is:
#     {"name": "rpi.lorawan", "is_active": true,
#      "serial_no": "D83ADDB44BDF", "hw_model": "RPI4B", ...}
# The ROLE is the dotted `name` string verbatim ("nxcore" / "rpi" /
# "rpi.lorawan" / "nxagent"). There is NO separate `zone` field on the public
# endpoint (the sage-gui TypeScript types showing `zone`/`rpi-shield` describe
# a different/internal schema and do not match the live response).

# Standard library
import json
import ssl
import time
import urllib.request
from urllib.error import HTTPError, URLError

# NOTE the TRAILING SLASH. Django serves this with APPEND_SLASH, so the
# slashless URL 301-redirects to the slashed one. We request the canonical
# URL directly to avoid the extra round trip.
_BASE = "https://auth.sagecontinuum.org/api/v-beta/nodes"

# The auth host can present a certificate the default context rejects (same
# quirk the data endpoint has). These are read-only public-metadata GETs, so
# we use an unverified context, matching how the dashboard notebook already
# treats sage endpoints.
_SSL_CTX = ssl._create_unverified_context()


class ManifestError(RuntimeError):
    """Raised when the manifest endpoint cannot be reached or returns bad data."""


def _fetch_json(url, timeout=15, retries=2, backoff=1.5):
    """GET `url` and parse JSON, with a couple of retries on transient errors."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(backoff ** attempt)
    raise ManifestError(f"could not fetch {url}: {last_err}") from last_err


def _parse_computes(node_obj):
    """Pull the compute roster out of one node object.

    Returns a list of dicts: {"name", "serial_no", "is_active", "hw_model"}.
    `name` is the role verbatim (e.g. "rpi.lorawan"). Entries with no
    serial_no are dropped (can't be joined to uptime data).
    """
    out = []
    for c in node_obj.get("computes", []) or []:
        serial = c.get("serial_no")
        if not serial:
            continue
        out.append({
            "name":      c.get("name"),
            "serial_no": serial,
            "is_active": bool(c.get("is_active", True)),
            "hw_model":  c.get("hw_model"),
        })
    return out


def get_node(vsn, timeout=15):
    """Fetch one node's manifest. Returns {"vsn", "site_id", "computes": [...]}.

    Raises ManifestError if unreachable. `computes` is the parsed roster
    (see _parse_computes).
    """
    url = f"{_BASE}/{vsn}/"
    obj = _fetch_json(url, timeout=timeout)
    if not isinstance(obj, dict):
        raise ManifestError(f"{url} did not return a node object (got {type(obj).__name__})")
    return {
        "vsn":      obj.get("vsn", vsn),
        "site_id":  obj.get("site_id"),
        "computes": _parse_computes(obj),
    }


def get_all_nodes(timeout=30):
    """Fetch every node's manifest. Returns {vsn: {"vsn","site_id","computes"}}.

    Raises ManifestError if unreachable. Keyed by vsn for easy lookup.
    """
    url = f"{_BASE}/"
    arr = _fetch_json(url, timeout=timeout)
    if not isinstance(arr, list):
        raise ManifestError(f"{url} did not return a list (got {type(arr).__name__})")
    nodes = {}
    for obj in arr:
        if not isinstance(obj, dict) or "vsn" not in obj:
            continue
        nodes[obj["vsn"]] = {
            "vsn":      obj["vsn"],
            "site_id":  obj.get("site_id"),
            "computes": _parse_computes(obj),
        }
    return nodes


# ---------------------------------------------------------------------------
# Host <-> serial join (matches the portal's findHostWithSerial exactly)
# ---------------------------------------------------------------------------
#
# sage_data_client carries the host serial in meta.host as a zero-padded,
# lowercase, suffixed string:  "0000d83addb44bdf.ws-rpi". The manifest gives
# the bare uppercase serial: "D83ADDB44BDF".
#
# The portal join is:  host.split('.')[0].slice(4).toUpperCase() == serial
# i.e. take the part before the first '.', DROP THE FIRST 4 CHARS (the fixed
# zero pad), uppercase, compare. We deliberately strip a FIXED 4 chars rather
# than lstrip('0'): a serial whose real first nibble is '0' (e.g. 0CA6...)
# would be corrupted by lstrip but is handled correctly by the fixed slice.
# Splitting on '.' (not a known suffix) means every host type works for free:
# .ws-rpi / .ws-nxcore / .ws-nxagent and blade names alike.


def host_to_serial(meta_host):
    """'0000d83addb44bdf.ws-rpi' -> 'D83ADDB44BDF'. None if unparseable."""
    if not isinstance(meta_host, str) or "." not in meta_host:
        return None
    prefix = meta_host.split(".")[0]
    if len(prefix) <= 4:
        return None
    return prefix[4:].upper()


def find_host_for_serial(hosts, serial_no):
    """Return the meta.host in `hosts` whose serial matches serial_no, or None."""
    if not serial_no:
        return None
    target = serial_no.upper()
    for h in hosts:
        if host_to_serial(h) == target:
            return h
    return None

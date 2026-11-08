#!/usr/bin/python
# pad8bitdo - userspace driver for 8BitDo 2.4G receivers (Xbox 360 protocol) on rooted LG webOS TVs.
#
# Why: the TV's kernel (4.4) xpad driver does not know the 8BitDo receiver ID, and even when the ID
# is added it never sends the start/LED requests the receiver waits for, so no input arrives.
# This daemon talks to the receiver over usbfs, wakes it up the way Windows does, and exposes a
# virtual Xbox 360 pad through /dev/uinput, laid out exactly like the xpad driver would.
#
# Python 2.7, ARM32. No dependencies beyond the standard library.
# https://github.com/artor410/webOS6-8bitdo-receiver-driver
import os, sys, time, errno, fcntl, struct, ctypes, signal, select, threading, array

RECEIVERS = {("2dc8", "310a")}          # 8BitDo Ultimate 2C Wireless (XInput mode)
LOG = "/tmp/pad8bitdo.log"
PIDFILE = "/tmp/pad8bitdo.pid"

# usbfs ioctls (ARM32 layouts)
USBDEVFS_CONTROL = 0xC0105500
USBDEVFS_BULK = 0xC0105502
USBDEVFS_CLAIMINTERFACE = 0x8004550F
USBDEVFS_RELEASEINTERFACE = 0x80045510

# uinput
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT = 0x40045564, 0x40045565, 0x40045567
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
BUS_USB = 0x03

# uinput force feedback (rumble). ARM32 sizes: struct ff_effect = 44, uinput_ff_upload = 96,
# uinput_ff_erase = 12.
EV_FF, EV_UINPUT = 0x15, 0x0101
FF_RUMBLE, FF_GAIN = 0x50, 0x60
UI_FF_UPLOAD, UI_FF_ERASE = 1, 2
UI_SET_FFBIT = 0x4004556B
UI_BEGIN_FF_UPLOAD, UI_END_FF_UPLOAD = 0xC06055C8, 0x406055C9
UI_BEGIN_FF_ERASE, UI_END_FF_ERASE = 0xC00C55CA, 0x400C55CB
FF_EFFECTS_MAX = 16

# Same button/axis layout as the kernel xpad driver for an Xbox 360 pad
BTN = dict(A=0x130, B=0x131, X=0x133, Y=0x134, TL=0x136, TR=0x137,
           SELECT=0x13a, START=0x13b, MODE=0x13c, THUMBL=0x13d, THUMBR=0x13e)
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_HAT0X, ABS_HAT0Y = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x10, 0x11
# (report byte, mask) -> key
BUTTON_MAP = [
    (2, 0x10, BTN["START"]), (2, 0x20, BTN["SELECT"]), (2, 0x40, BTN["THUMBL"]), (2, 0x80, BTN["THUMBR"]),
    (3, 0x01, BTN["TL"]), (3, 0x02, BTN["TR"]), (3, 0x04, BTN["MODE"]),
    (3, 0x10, BTN["A"]), (3, 0x20, BTN["B"]), (3, 0x40, BTN["X"]), (3, 0x80, BTN["Y"]),
]

libc = ctypes.CDLL(None, use_errno=True)
running = True


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 200000:
            os.rename(LOG, LOG + ".1")
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except IOError:
        return None


def find_receiver():
    base = "/sys/bus/usb/devices"
    for name in os.listdir(base):
        if ":" in name:
            continue
        d = os.path.join(base, name)
        if (read(d + "/idVendor"), read(d + "/idProduct")) in RECEIVERS:
            return name, "/dev/bus/usb/%03d/%03d" % (int(read(d + "/busnum")), int(read(d + "/devnum")))
    return None


def release_from_kernel(devname):
    intf = devname + ":1.0"
    drv = "/sys/bus/usb/devices/%s/driver" % intf
    if os.path.islink(drv):
        drvname = os.path.basename(os.readlink(drv))
        if drvname != "usbfs":
            with open(drv + "/unbind", "w") as f:
                f.write(intf)
            log("interface 0 released from kernel driver %s" % drvname)


def ioctl_ret(fd, req, arg):
    r = libc.ioctl(fd, req, ctypes.c_char_p(arg))
    if r < 0:
        e = ctypes.get_errno()
        raise IOError(e, os.strerror(e))
    return r


class Receiver(object):
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR)
        fcntl.ioctl(self.fd, USBDEVFS_CLAIMINTERFACE, struct.pack("<I", 0))

    def control_in(self, reqtype, req, value, index, length):
        buf = ctypes.create_string_buffer(length)
        ioctl_ret(self.fd, USBDEVFS_CONTROL,
                  struct.pack("<BBHHHII", reqtype, req, value, index, length, 1000, ctypes.addressof(buf)))
        return buf.raw

    def xfer(self, ep, data_or_len, timeout_ms):
        if isinstance(data_or_len, int):
            buf, ln = ctypes.create_string_buffer(data_or_len), data_or_len
        else:
            buf, ln = ctypes.create_string_buffer(data_or_len, len(data_or_len)), len(data_or_len)
        n = ioctl_ret(self.fd, USBDEVFS_BULK, struct.pack("<IIII", ep, ln, timeout_ms, ctypes.addressof(buf)))
        return buf.raw[:n]

    def wake(self):
        # What the Windows XInput driver sends first; the receiver stays silent without it.
        self.control_in(0xC1, 0x01, 0x0100, 0x0000, 20)
        # LED: player 1
        self.xfer(0x05, "\x01\x03\x02", 500)

    def rumble(self, strong, weak):
        # Xbox 360 rumble report: big (left/strong) and small (right/weak) motor, 0-255 each
        self.xfer(0x05, struct.pack("8B", 0x00, 0x08, 0x00, strong, weak, 0, 0, 0), 200)

    def close(self):
        try:
            fcntl.ioctl(self.fd, USBDEVFS_RELEASEINTERFACE, struct.pack("<I", 0))
        except IOError:
            pass
        os.close(self.fd)


class VirtualPad(object):
    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_RDWR | os.O_NONBLOCK)
        for ev in (EV_KEY, EV_ABS, EV_SYN, EV_FF):
            fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
        fcntl.ioctl(self.fd, UI_SET_FFBIT, FF_RUMBLE)
        fcntl.ioctl(self.fd, UI_SET_FFBIT, FF_GAIN)
        self.effects = {}       # effect id -> (strong 0-255, weak 0-255, length ms)
        self.gain = 0xFFFF
        self.playing = None     # effect id currently playing
        self.stop_at = None     # time to stop a timed effect
        self.motors = (0, 0)
        for key in BTN.values():
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, key)
        absmax, absmin, absfuzz, absflat = [0] * 64, [0] * 64, [0] * 64, [0] * 64
        for a in (ABS_X, ABS_Y, ABS_RX, ABS_RY):
            absmin[a], absmax[a], absfuzz[a], absflat[a] = -32768, 32767, 16, 128
        for a in (ABS_Z, ABS_RZ):
            absmin[a], absmax[a] = 0, 255
        for a in (ABS_HAT0X, ABS_HAT0Y):
            absmin[a], absmax[a] = -1, 1
        for a in (ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_HAT0X, ABS_HAT0Y):
            fcntl.ioctl(self.fd, UI_SET_ABSBIT, a)
        # Present as a wired Xbox 360 pad so every game-controller database maps it correctly.
        name = "Microsoft X-Box 360 pad".ljust(80, "\0")
        dev = struct.pack("<80sHHHHI", name, BUS_USB, 0x045e, 0x028e, 0x0114, FF_EFFECTS_MAX)
        dev += struct.pack("<64i", *absmax) + struct.pack("<64i", *absmin)
        dev += struct.pack("<64i", *absfuzz) + struct.pack("<64i", *absflat)
        os.write(self.fd, dev)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        self.state = {}

    def update(self, report):
        if len(report) < 14 or ord(report[0]) != 0x00 or ord(report[1]) != 0x14:
            return
        b = [ord(c) for c in report]
        new = {}
        for byte, mask, key in BUTTON_MAP:
            new[(EV_KEY, key)] = 1 if b[byte] & mask else 0
        new[(EV_ABS, ABS_HAT0X)] = (1 if b[2] & 0x08 else 0) - (1 if b[2] & 0x04 else 0)
        new[(EV_ABS, ABS_HAT0Y)] = (1 if b[2] & 0x02 else 0) - (1 if b[2] & 0x01 else 0)
        new[(EV_ABS, ABS_Z)] = b[4]
        new[(EV_ABS, ABS_RZ)] = b[5]
        lx, ly, rx, ry = struct.unpack("<hhhh", report[6:14])
        new[(EV_ABS, ABS_X)] = lx
        new[(EV_ABS, ABS_Y)] = ~ly          # xpad inverts Y
        new[(EV_ABS, ABS_RX)] = rx
        new[(EV_ABS, ABS_RY)] = ~ry
        out = []
        for k, v in new.items():
            if self.state.get(k) != v:
                out.append(struct.pack("<IIHHi", 0, 0, k[0], k[1], v))
        if out:
            out.append(struct.pack("<IIHHi", 0, 0, EV_SYN, 0, 0))
            os.write(self.fd, "".join(out))
            self.state = new

    # ---- rumble -------------------------------------------------------------------------------
    def _set_motors(self, rx, strong, weak):
        scale = self.gain / 65535.0
        m = (int(strong * scale), int(weak * scale))
        if m != self.motors:
            rx.rumble(*m)
            self.motors = m

    def _upload(self, request_id):
        buf = array.array("B", struct.pack("<Ii", request_id, 0) + "\0" * 88)
        fcntl.ioctl(self.fd, UI_BEGIN_FF_UPLOAD, buf, True)
        raw = buf.tostring()
        # struct ff_effect at offset 8: type u16, id s16, direction u16, trigger 2xu16,
        # replay (length u16, delay u16), union at +16 (rumble: strong u16, weak u16)
        etype, eid = struct.unpack_from("<Hh", raw, 8)
        length = struct.unpack_from("<H", raw, 8 + 10)[0]
        if etype == FF_RUMBLE:
            strong, weak = struct.unpack_from("<HH", raw, 8 + 16)
            self.effects[eid] = (strong >> 8, weak >> 8, length)
            retval = 0
        else:
            retval = -errno.EINVAL
        out = array.array("B", raw[:4] + struct.pack("<i", retval) + raw[8:])
        fcntl.ioctl(self.fd, UI_END_FF_UPLOAD, out, True)

    def _erase(self, request_id, rx):
        buf = array.array("B", struct.pack("<IiI", request_id, 0, 0))
        fcntl.ioctl(self.fd, UI_BEGIN_FF_ERASE, buf, True)
        eid = struct.unpack_from("<I", buf.tostring(), 8)[0]
        self.effects.pop(eid, None)
        if self.playing == eid:
            self.playing, self.stop_at = None, None
            self._set_motors(rx, 0, 0)
        fcntl.ioctl(self.fd, UI_END_FF_ERASE, buf, True)

    def handle_ff(self, rx):
        """Process pending force-feedback requests from apps. Called from the rumble thread."""
        try:
            data = os.read(self.fd, 16 * 32)
        except OSError as e:
            if e.errno == errno.EAGAIN:
                data = ""
            else:
                raise
        for i in range(0, len(data) - 15, 16):
            _, _, etype, code, value = struct.unpack_from("<IIHHi", data, i)
            if etype == EV_UINPUT and code == UI_FF_UPLOAD:
                self._upload(value)
            elif etype == EV_UINPUT and code == UI_FF_ERASE:
                self._erase(value, rx)
            elif etype == EV_FF and code == FF_GAIN:
                self.gain = max(0, min(0xFFFF, value))
            elif etype == EV_FF and code in self.effects:
                strong, weak, length = self.effects[code]
                if value > 0:
                    self.playing = code
                    self.stop_at = time.time() + length / 1000.0 if length else None
                    self._set_motors(rx, strong, weak)
                elif self.playing == code:
                    self.playing, self.stop_at = None, None
                    self._set_motors(rx, 0, 0)
        if self.stop_at and time.time() >= self.stop_at:
            self.playing, self.stop_at = None, None
            self._set_motors(rx, 0, 0)

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except IOError:
            pass
        os.close(self.fd)


def serve(devname, path):
    release_from_kernel(devname)
    rx = Receiver(path)
    pad = None
    done = threading.Event()
    rumble_thread = None

    def rumble_loop():
        # Apps send rumble requests to the virtual pad; forward them to the receiver.
        while not done.is_set():
            try:
                select.select([pad.fd], [], [], 0.05)
                pad.handle_ff(rx)
            except (IOError, OSError) as e:
                if not done.is_set():
                    log("rumble error (%s)" % e)
                time.sleep(0.2)

    try:
        rx.wake()
        pad = VirtualPad()
        rumble_thread = threading.Thread(target=rumble_loop)
        rumble_thread.daemon = True
        rumble_thread.start()
        log("receiver %s ready, virtual Xbox 360 pad created (rumble on)" % path)
        while running:
            try:
                pad.update(rx.xfer(0x84, 32, 1000))
            except IOError as e:
                if e.errno == errno.ETIMEDOUT:
                    continue
                log("receiver gone (%s)" % e)
                return
    finally:
        done.set()
        if rumble_thread:
            rumble_thread.join(1)
        if pad:
            pad.close()
        rx.close()


def stop(*_):
    global running
    running = False


def main():
    if os.path.exists(PIDFILE):
        old = read(PIDFILE)
        if old and os.path.exists("/proc/%s" % old):
            sys.exit(0)
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log("pad8bitdo started")
    waiting_logged = False
    while running:
        found = find_receiver()
        if not found:
            if not waiting_logged:
                log("waiting for receiver")
                waiting_logged = True
            time.sleep(1)
            continue
        waiting_logged = False
        try:
            serve(*found)
        except Exception as e:
            log("error: %r" % (e,))
        time.sleep(1)
    log("pad8bitdo stopped")
    try:
        os.remove(PIDFILE)
    except OSError:
        pass


if __name__ == "__main__":
    main()

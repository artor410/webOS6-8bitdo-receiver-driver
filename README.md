# webOS6-8bitdo-receiver-driver

**Use an 8BitDo controller with its 2.4G USB receiver on a rooted LG webOS TV.**

Out of the box, an LG webOS 6 TV doesn't recognize the 8BitDo 2.4G receiver as a controller. At best it shows up as a "Generic X-Box pad" that does nothing when you press buttons. This small driver fixes that: plug in the receiver, and apps like [punktfunk](https://punktfunk.unom.io/) and Moonlight see a normal **Xbox 360 controller**.

## At a glance

| | |
|---|---|
| Works with | 8BitDo Ultimate 2C Wireless, 2.4G receiver (`2dc8:310a`) |
| Tested on | LG OLED55A1PSA, webOS 6 (SDK 6.5.3, firmware 03.53.45, kernel 4.4.84) |
| Shows up as | Xbox 360 controller (sticks, triggers, D-pad, all buttons including Guide) |
| Reconnects | Yes. Turning the controller off and on, or replugging the receiver, is picked up in about 2 seconds |
| Starts with the TV | Yes, through Homebrew Channel's boot scripts |
| Rumble | Yes, both motors (tested in F1 22 through punktfunk) |

## Requirements

- The TV must be **rooted** and have **[Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel)** installed. See [webosbrew.org](https://www.webosbrew.org/) for how to root it.
- **SSH as root** enabled in Homebrew Channel.
- A free USB port for the receiver.

## Install

1. Connect to the TV over SSH as `root`.
2. Run:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/artor410/webOS6-8bitdo-receiver-driver/main/install.sh | sh
   ```

3. Plug the receiver into the TV and turn the controller on (in its 2.4G / Xbox mode).
4. **Close and reopen** your streaming app. Apps look for controllers when they start.

That's it. The driver now starts by itself every time the TV boots.

## Check that it works

```sh
cat /tmp/pad8bitdo.log
```

You should see a line like `receiver /dev/bus/usb/002/005 ready, virtual Xbox 360 pad created (rumble on)`.

The new controller is also listed here, as `Microsoft X-Box 360 pad`:

```sh
grep -A4 "X-Box 360" /proc/bus/input/devices
```

## Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/artor410/webOS6-8bitdo-receiver-driver/main/uninstall.sh | sh
```

This removes the driver, its boot hook and its logs. Nothing else on the TV is changed.

## How it works

There are two problems on webOS 6's kernel (4.4), and the driver gets around both from user space, without kernel modules:

1. **The kernel doesn't know the receiver.** Its `xpad` driver predates 8BitDo's USB ID, so the gamepad interface stays unbound. The TV only sees the receiver's keyboard/mouse interfaces.
2. **The receiver stays silent until it's woken up.** Even if you teach `xpad` the ID (`echo "2dc8 310a ff" > /sys/bus/usb/drivers/xpad/new_id`), no input arrives. The receiver waits for what the Windows XInput driver sends first: a vendor control request (`0xC1 / 0x01`, value `0x0100`, 20 bytes) followed by an LED command. The TV's old `xpad` sends neither.

`pad8bitdo.py`:

- watches for the receiver;
- claims its gamepad interface through `usbfs`;
- sends the start request and the LED command;
- reads the standard 20-byte Xbox 360 reports;
- feeds them to a virtual controller created with `/dev/uinput`;
- forwards rumble the other way. The virtual controller supports force feedback (`FF_RUMBLE`), and every rumble an app asks for is sent to the receiver as an Xbox 360 rumble report, with separate strong and weak motors.

The virtual controller uses the same buttons and axes as the kernel `xpad` driver, and identifies as a wired Xbox 360 pad (`045e:028e`), so game-controller databases (SDL etc.) map it correctly.

It's a single Python 2.7 file using only the standard library, since webOS 6 ships `/usr/bin/python`. It uses almost no CPU: it sleeps until the receiver sends a report.

## Files

| File | What it is |
|---|---|
| `pad8bitdo.py` | The driver. Installed to `/home/root/pad8bitdo/` |
| `init.d/60-pad8bitdo` | Boot hook. Installed to `/var/lib/webosbrew/init.d/` |
| `install.sh` / `uninstall.sh` | One-line install and removal, run on the TV |

## Other 8BitDo receivers

Only the Ultimate 2C receiver (`2dc8:310a`) has been tested. Other 8BitDo receivers in Xbox/XInput mode probably work the same way. To try one:

1. Find its ID with `cat /sys/bus/usb/devices/*/idVendor /sys/bus/usb/devices/*/idProduct`.
2. Add it to `RECEIVERS` at the top of `pad8bitdo.py`.
3. Run `sh /var/lib/webosbrew/init.d/60-pad8bitdo`.

If it works (or doesn't), please open an issue with the ID and your TV model.

## Troubleshooting

- **The controller isn't detected in the app:** close and reopen the app after the log says `virtual Xbox 360 pad created`.
- **Nothing in the log:** check the driver is running with `cat /tmp/pad8bitdo.pid`. Start it by hand with `sh /var/lib/webosbrew/init.d/60-pad8bitdo`. Errors go to `/tmp/pad8bitdo.err`.
- **`waiting for receiver` and nothing else:** the controller is probably off, or not paired to the receiver. While it's unpaired, the receiver shows up as `2dc8:301c` ("8BitDo IDLE").

## Related

- [webOS6-usbrealtek-driver](https://github.com/artor410/webOS6-usbrealtek-driver): faster wired networking with Realtek USB Ethernet adapters (RTL8152/RTL8153) on the same TVs. Handy for high-bitrate game streaming.

## License

MIT. See [LICENSE](LICENSE).
